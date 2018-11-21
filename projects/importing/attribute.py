import logging
from collections import Counter, defaultdict
from itertools import filterfalse
from typing import Iterable, Sequence

from django.db import transaction
from openpyxl import load_workbook

from projects.models import (
    FieldSetAttribute,
    ProjectPhaseSection,
    ProjectPhaseSectionAttribute,
)
from ..models import Attribute, ProjectPhase, ProjectType
from ..models.utils import create_identifier, truncate_identifier

logger = logging.getLogger(__name__)

IDENTIFIER_MAX_LENGTH = 50

DEFAULT_SHEET_NAME = "Hanketiedot (työversio)"

ATTRIBUTE_NAME = "hanketieto"
ATTRIBUTE_TYPE = "tietotyyppi"
ATTRIBUTE_REQUIRED = (
    "pakollinen tieto (jos ei niin kohdan voi valita poistettavaksi)"
)  # kyllä/ei
PHASE_SECTION_NAME = "minkä väliotsikon alle kuuluu"
PUBLIC_ATTRIBUTE = "julkinen tieto"  # kyllä/ei julkinen
HELP_TEXT = "ohje"
METADATA_FIELDS = {
    "project_cards": {
        "normal": "normaali hankekortti",
        "extended": "laajennettu hankekortti",
    }
}

ATTRIBUTE_FIELDSET = "hanketieto fieldset"

ATTRIBUTE_PHASE_COLUMNS = [
    "syöttövaihe",
    "päivitys-vaihe 2",
    "päivitys-vaihe 3",
    "päivitys-vaihe 4",
]

EXPECTED_A1_VALUE = ATTRIBUTE_NAME

PROJECT_PHASES = [
    {"name": "Käynnistys", "color": "color--tram", "color_code": "#009246"},  # None
    # {'name': 'Suunnitteluperiaatteet', 'color': '#009142'},
    {"name": "OAS", "color": "color--summer", "color_code": "#ffc61e"},  # 01, 03
    # {'name': 'Luonnos', 'color': '#ffd600'},
    {"name": "Ehdotus", "color": "color--metro", "color_code": "#fd4f00"},  # 02, 04
    {
        "name": "Tarkistettu ehdotus",
        "color": "color--bus",
        "color_code": "#0000bf",
    },  # 05, 07
    {
        "name": "Kanslia-Khs-Valtuusto",
        "color": "color--black",
        "color_code": "#000000",
    },  # 06, 07 <- Kvsto
    {"name": "Voimaantulo", "color": "color--white", "color_code": "#ffffff"},
]

# projektin vuosi <- tarkistetun ehdotuksen lautakuntapvm

VALUE_TYPES = {
    "fieldset": Attribute.TYPE_FIELDSET,
    "sisältö; nimi": Attribute.TYPE_SHORT_STRING,
    "tunniste; numerotunniste": Attribute.TYPE_SHORT_STRING,
    "tunniste; numero": Attribute.TYPE_SHORT_STRING,
    "sisältö; teksti": Attribute.TYPE_LONG_STRING,
    "spatiaalinen": Attribute.TYPE_GEOMETRY,
    "sisältö; kuva": Attribute.TYPE_IMAGE,
    "aikataulu ja tehtävät; pvm": Attribute.TYPE_DATE,
    "aikataulu ja tehtävät; teksti": Attribute.TYPE_LONG_STRING,
    "sisältö; laaja teksti": Attribute.TYPE_LONG_STRING,
    "sisältö; vuosiluku": Attribute.TYPE_SHORT_STRING,
    "sisältö; vuosilukuja (1...n)": Attribute.TYPE_LONG_STRING,  # TODO Multiple years
    "sisältö; numero": Attribute.TYPE_INTEGER,  # TODO Also decimal?
    "sisältö; valitaan kyllä/ei": Attribute.TYPE_BOOLEAN,  # TODO or kyllä/ei/ei asetettu?
    "aikataulu ja tehtävät; kyllä/ei": Attribute.TYPE_BOOLEAN,  # TODO or kyllä/ei/ei asetettu?
    "sisältö; tekstivalikko": Attribute.TYPE_LONG_STRING,  # TODO Choice of values
    "sisältö; valitaan yksi viidestä": Attribute.TYPE_SHORT_STRING,  # TODO e.g. project size, choice of values
    "aikataulu ja tehtävät; valitaan toinen": Attribute.TYPE_SHORT_STRING,  # TODO Choice of values
    "resurssit; valintalista Hijatista": Attribute.TYPE_USER,  # TODO User select or responsible unit
    "sisältö; luettelo": Attribute.TYPE_LONG_STRING,  # TODO List of things
    "sisältö; pvm": Attribute.TYPE_DATE,  # TODO Might need to contain multiple dates
    "sisältö; osoite": Attribute.TYPE_LONG_STRING,  # TODO Might need to contain multiple addresses
    "sisältö; kaavanumero(t)": Attribute.TYPE_LONG_STRING,  # TODO List of identifiers
    "sisältö; kyllä/ei": Attribute.TYPE_BOOLEAN,  # TODO or kyllä/ei/ei asetettu?
    "talous; teksti": Attribute.TYPE_LONG_STRING,  # TODO List of strings
    "talous; numero (€)": Attribute.TYPE_LONG_STRING,  # TODO Might have multiple values
    "talous; kyllä/ei": Attribute.TYPE_BOOLEAN,  # TODO or kyllä/ei/ei asetettu?
    "aikataulu ja tehtävät; pvm ja paikka": Attribute.TYPE_LONG_STRING,  # TODO Time and place
    "sisältö; vakioteksti": Attribute.TYPE_LONG_STRING,  # TODO Text always the same
    "sisältö; valitaan toinen": Attribute.TYPE_SHORT_STRING,  # TODO Choice
    "aikataulu ja tehtävät; vaihe 1…6": Attribute.TYPE_SHORT_STRING,  # TODO Choice
    "sisältö; teksti (automaattinen täyttö?)": Attribute.TYPE_LONG_STRING,  # TODO Generated
    "sisältö; kyllä/ei/tieto puuttuu": Attribute.TYPE_BOOLEAN,  # TODO Boolean or choice?
}


class AttributeImporterException(Exception):
    pass


class AttributeImporter:
    """Import attributes and project phase sections for asemakaava project type from the given Excel."""

    def __init__(self, options=None):
        self.options = options

    def _open_workbook(self, filename):
        try:
            return load_workbook(filename, read_only=True, data_only=True)
        except FileNotFoundError as e:
            raise AttributeImporterException(e)

    def _extract_data_from_workbook(self, workbook):
        try:
            sheet = workbook[self.options.get("sheet") or DEFAULT_SHEET_NAME]
        except KeyError as e:
            raise AttributeImporterException(e)

        primary_sheet_value = sheet["A1"].value
        if primary_sheet_value and primary_sheet_value.lower() != EXPECTED_A1_VALUE:
            raise AttributeImporterException(
                "This does not seem to be a valid attribute sheet."
            )

        data = []

        for row in sheet.iter_rows():
            if not row[0].value:
                break
            data.append([col.value for col in row])

        return data

    def _set_row_indexes(self, header_row: Iterable[str]):
        """Determine index number for all columns."""
        self.column_index: dict = {}

        for index, column in enumerate(header_row):
            if column:
                self.column_index[column.lower()] = index

    def _check_if_row_valid(self, row: Sequence) -> bool:
        """Check if the row has all required data.

        For importing a field the requirements are:
        - Name
        - Type
        - Is part of a phase
        - Phase section name has been defined
        """
        name = row[self.column_index[ATTRIBUTE_NAME]]
        attr_type = row[self.column_index[ATTRIBUTE_TYPE]]
        belongs_to_phase = bool(self._get_attribute_input_phases(row))
        phase_has_name = bool(row[self.column_index[PHASE_SECTION_NAME]])

        if name and attr_type and belongs_to_phase and phase_has_name:
            return True

        logger.info(f"Field {name} is not valid, it will not be imported.")
        return False

    def _row_part_of_fieldset(self, row: Sequence) -> bool:
        """Check if the row should be a part of a fieldset."""
        if ATTRIBUTE_FIELDSET not in self.column_index:
            return False
        fieldset_value = row[self.column_index[ATTRIBUTE_FIELDSET]]
        return bool(fieldset_value)

    def _get_identifier_for_value(self, value: str) -> str:
        identifier = create_identifier(value.strip(" \t:."))
        return truncate_identifier(identifier, length=IDENTIFIER_MAX_LENGTH)

    def _get_attribute_row_identifier(self, row: Sequence) -> str:
        return self._get_identifier_for_value(row[self.column_index[ATTRIBUTE_NAME]])

    def _update_attributes(self, rows: Iterable[Sequence[str]]):
        logger.info("\nUpdating attributes...")

        for row in rows:
            identifier = self._get_attribute_row_identifier(row)

            name = row[self.column_index[ATTRIBUTE_NAME]].strip(" \t:.")

            value_type_string = row[self.column_index[ATTRIBUTE_TYPE]]
            value_type = (
                VALUE_TYPES.get(value_type_string.strip())
                if value_type_string
                else None
            )

            try:
                help_text = row[self.column_index[HELP_TEXT]].strip()
            except (IndexError, AttributeError):
                help_text = ""

            is_public = row[self.column_index[PUBLIC_ATTRIBUTE]] == "kyllä"
            is_required = row[self.column_index[ATTRIBUTE_REQUIRED]] == "kyllä"

            if not value_type:
                logger.warning(
                    f'Unidentified value type "{value_type_string}", defaulting to short string'
                )
                value_type = Attribute.TYPE_SHORT_STRING

            overwrite = self.options.get("overwrite")

            if overwrite:
                method = Attribute.objects.update_or_create
            else:
                method = Attribute.objects.get_or_create

            attribute, created = method(
                identifier=identifier,
                defaults={
                    "name": name,
                    "value_type": value_type,
                    "help_text": help_text,
                    "public": is_public,
                    "required": is_required,
                },
            )

            if created:
                action_str = "Created"
            else:
                action_str = "Updated" if overwrite else "Already exists, skipping"

            logger.info(f"{action_str} {attribute}")

    def _replace_fieldset_links(self, rows: Iterable[Sequence[str]]):
        logger.info("\nUpdating fieldsets...")

        if ATTRIBUTE_FIELDSET not in self.column_index:
            logger.warning(f'Fieldset column "{ATTRIBUTE_FIELDSET}" missing: Skipping')
            return

        FieldSetAttribute.objects.all().delete()
        fieldset_map = defaultdict(list)

        # Map out the link that need to be created
        for row in rows:
            fieldset_attr = row[self.column_index[ATTRIBUTE_FIELDSET]]
            if not fieldset_attr:
                continue

            attr_id = self._get_attribute_row_identifier(row)
            fieldset_attr_id = self._get_identifier_for_value(fieldset_attr)

            fieldset_map[fieldset_attr_id].append(attr_id)

        # Create the links
        for source_id in fieldset_map:
            source = Attribute.objects.get(identifier=source_id)

            for index, target_id in enumerate(fieldset_map[source_id], start=1):
                target = Attribute.objects.get(identifier=target_id)
                fsa = FieldSetAttribute.objects.create(
                    attribute_source=source, attribute_target=target, index=index
                )
                logger.info(f"Created {fsa}")

    def _get_attribute_input_phases(self, row):
        input_phases = []

        for column_name in ATTRIBUTE_PHASE_COLUMNS:
            value = row[self.column_index[column_name]]
            if value is None:
                continue

            try:
                value = int(value)
                input_phases.append(value)
            except ValueError:
                logger.info(f"Cannot covert {value} into an integer.")

        return filter(lambda x: x is not None, input_phases)

    def _update_sections(self, rows):
        logger.info("\nUpdating sections...")

        for phase in ProjectPhase.objects.filter(project_type=self.project_type):

            # Get all distinct section names in appearance order
            phase_sections = []

            for row in rows:
                section_phase_name = row[self.column_index[PHASE_SECTION_NAME]].strip()

                if (
                    phase.index in self._get_attribute_input_phases(row)
                    and section_phase_name not in phase_sections
                ):
                    phase_sections.append(section_phase_name)

            for i, phase_section_name in enumerate(phase_sections, start=1):
                overwrite = self.options.get("overwrite")

                if overwrite:
                    method = ProjectPhaseSection.objects.update_or_create
                else:
                    method = ProjectPhaseSection.objects.get_or_create

                section, created = method(
                    phase=phase, index=i, defaults={"name": phase_section_name}
                )

                if created:
                    action_str = "Created"
                else:
                    action_str = "Updated" if overwrite else "Already exists, skipping"

                logger.info(f"{action_str} {section}")

    def _replace_attribute_section_links(self, rows):
        logger.info("\nReplacing attribute section links...")

        ProjectPhaseSectionAttribute.objects.filter(
            section__phase__project_type=self.project_type
        ).delete()

        for phase in ProjectPhase.objects.filter(project_type=self.project_type):

            # Index for attribute within a phase section
            counter = Counter()

            for row in rows:
                identifier = self._get_attribute_row_identifier(row)
                attribute = Attribute.objects.get(identifier=identifier)

                if phase.index not in self._get_attribute_input_phases(row):
                    # Attribute doesn't appear in this phase
                    continue

                section_phase_name = row[self.column_index[PHASE_SECTION_NAME]].strip()

                section = ProjectPhaseSection.objects.get(
                    phase=phase, name=section_phase_name
                )

                section_attribute = ProjectPhaseSectionAttribute.objects.create(
                    attribute=attribute, section=section, index=counter[section]
                )

                counter[section] += 1

                logger.info(
                    f"Created "
                    f"{section_attribute.section.phase} / "
                    f"{section_attribute.section} / "
                    f"{section_attribute.index} / "
                    f"{section_attribute.attribute}"
                )

    def _update_type_metadata(self, rows):
        metadata = {}
        metadata.update(self._get_project_card_attributes_metadata(rows))

        self.project_type.metadata = metadata
        self.project_type.save()

    def _get_project_card_attributes_metadata(self, rows) -> dict:
        metadata = {}
        project_card_mapping = {
            key: {} for key in METADATA_FIELDS["project_cards"].keys()
        }
        for row in rows:
            identifier = self._get_attribute_row_identifier(row)

            for card_type in project_card_mapping.keys():
                card_index = row[
                    self.column_index[METADATA_FIELDS["project_cards"][card_type]]
                ]

                if not card_index:
                    continue

                try:
                    card_index = int(card_index)
                    project_card_mapping[card_type][identifier] = card_index
                except ValueError:
                    logger.info(
                        f"Metadata: Cannot covert {card_index} into an integer."
                    )

        for card_type in project_card_mapping.keys():
            metadata_key = f"{card_type}_project_card_attributes"
            metadata[metadata_key] = sorted(
                project_card_mapping[card_type], key=project_card_mapping[card_type].get
            )
        return metadata

    def create_phases(self):
        logger.info("\nCreating phases...")
        current_phases = [
            obj.name for obj in self.project_type.phases.order_by("index")
        ]
        new_phases = [x["name"] for x in PROJECT_PHASES]
        if current_phases == new_phases:
            return

        self.project_type.phases.all().delete()
        for i, phase in enumerate(PROJECT_PHASES, start=1):
            ProjectPhase.objects.create(
                project_type=self.project_type,
                name=phase["name"],
                index=i,
                color=phase["color"],
                color_code=phase["color_code"],
            )

    @transaction.atomic
    def run(self):
        self.project_type, _ = ProjectType.objects.get_or_create(name="asemakaava")

        filename = self.options.get("filename")
        logger.info(
            f"Importing attributes from file {filename} for project type {self.project_type}..."
        )

        self.create_phases()

        workbook = self._open_workbook(filename)
        rows = self._extract_data_from_workbook(workbook)

        header_row = rows[0]
        self._set_row_indexes(header_row)

        data_rows = list(filter(self._check_if_row_valid, rows[1:]))

        self._update_attributes(data_rows)
        self._replace_fieldset_links(data_rows)

        # Remove all attributes from further processing that were part of a fieldset
        data_rows = list(filterfalse(self._row_part_of_fieldset, data_rows))

        self._update_sections(data_rows)
        self._replace_attribute_section_links(data_rows)
        self._update_type_metadata(data_rows)

        logger.info("Phases {}".format(ProjectPhase.objects.count()))
        logger.info("Attributes {}".format(Attribute.objects.count()))
        logger.info(
            "FieldSets {}".format(
                Attribute.objects.filter(value_type=Attribute.TYPE_FIELDSET).count()
            )
        )
        logger.info("Phase sections {}".format(ProjectPhaseSection.objects.count()))
        logger.info(
            "Phase section attributes {}".format(
                ProjectPhaseSectionAttribute.objects.count()
            )
        )
        logger.info("Import done.")
