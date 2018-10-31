import logging
from collections import Counter
from typing import Iterable, Sequence

from django.db import transaction
from openpyxl import load_workbook

from projects.models import ProjectPhaseSection, ProjectPhaseSectionAttribute
from ..models import Attribute, ProjectPhase, ProjectType
from ..models.utils import create_identifier, truncate_identifier

logger = logging.getLogger(__name__)

IDENTIFIER_MAX_LENGTH = 50
EXPECTED_A1_VALUE = "HANKETIETO"

DEFAULT_SHEET_NAME = "kaikki tiedot (keskeneräinen)"

ATTRIBUTE_NAME = "HANKETIETO"
ATTRIBUTE_TYPE = "TIETOTYYPPI"
ATTRIBUTE_REQUIRED = (
    "pakollinen tieto (jos EI niin kohdan voi valita poistettavaksi)"
)  # kyllä/ei
PHASE_SECTION_NAME = "Minkä VÄLIOTSIKON alle kuuluu"
PUBLIC_ATTRIBUTE = "JULKINEN TIETO"  # kyllä/ei julkinen
HELP_TEXT = "OHJE"

ATTRIBUTE_PHASE_COLUMNS = [
    "syöttövaihe",
    "Päivitys-vaihe 2",
    "Päivitys-vaihe 3",
    "Päivitys-vaihe 4",
]

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
}


class AttributeImporterException(Exception):
    pass


class AttributeImporter:
    """Import attributes and project phase sections for asemakaava project type from the given Excel."""

    def __init__(self, options=None):
        self.options = options

    def _open_workbook(self, filename):
        try:
            return load_workbook(filename, read_only=True)
        except FileNotFoundError as e:
            raise AttributeImporterException(e)

    def _extract_data_from_workbook(self, workbook):
        try:
            sheet = workbook[self.options.get("sheet") or DEFAULT_SHEET_NAME]
        except KeyError as e:
            raise AttributeImporterException(e)

        if sheet["A1"].value != EXPECTED_A1_VALUE:
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
            self.column_index[column] = index

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

    def _get_attribute_identifier(self, row: Sequence) -> str:
        identifier = create_identifier(
            row[self.column_index[ATTRIBUTE_NAME]].strip(" \t:.")
        )
        return truncate_identifier(identifier, length=IDENTIFIER_MAX_LENGTH)

    def _update_attributes(self, rows: Iterable[Sequence[str]]):
        logger.info("\nUpdating attributes...")

        for row in rows:
            identifier = self._get_attribute_identifier(row)

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
                },
            )

            if created:
                action_str = "Created"
            else:
                action_str = "Updated" if overwrite else "Already exists, skipping"

            logger.info(f"{action_str} {attribute}")

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
                identifier = self._get_attribute_identifier(row)
                attribute = Attribute.objects.get(identifier=identifier)

                if phase.index not in self._get_attribute_input_phases(row):
                    # Attribute doesn't appear in this phase
                    continue

                section_phase_name = row[self.column_index[PHASE_SECTION_NAME]].strip()

                section = ProjectPhaseSection.objects.get(
                    phase=phase, name=section_phase_name
                )

                is_required = row[self.column_index[ATTRIBUTE_REQUIRED]] == "kyllä"

                section_attribute = ProjectPhaseSectionAttribute.objects.create(
                    attribute=attribute,
                    section=section,
                    required=is_required,
                    index=counter[section],
                )

                counter[section] += 1

                logger.info(
                    f"Created "
                    f"{section_attribute.section.phase} / "
                    f"{section_attribute.section} / "
                    f"{section_attribute.index} / "
                    f"{section_attribute.attribute}"
                )

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
        self._update_sections(data_rows)
        self._replace_attribute_section_links(data_rows)

        logger.info("Phases {}".format(ProjectPhase.objects.count()))
        logger.info("Attributes {}".format(Attribute.objects.count()))
        logger.info("Phase sections {}".format(ProjectPhaseSection.objects.count()))
        logger.info(
            "Phase section attributes {}".format(
                ProjectPhaseSectionAttribute.objects.count()
            )
        )

        logger.info("Import done.")
