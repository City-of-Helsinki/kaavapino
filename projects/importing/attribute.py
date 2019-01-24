import itertools
import logging
import re
from collections import Counter, defaultdict
from enum import Enum
from itertools import filterfalse
from typing import Iterable, Sequence, List, Optional

from django.db import transaction
from django.db.models import ProtectedError
from openpyxl import load_workbook

from ..models import (
    Attribute,
    AttributeValueChoice,
    FieldSetAttribute,
    ProjectPhaseSection,
    ProjectPhaseSectionAttribute,
    ProjectPhase,
    ProjectType,
    ProjectSubtype,
)
from ..models.utils import create_identifier, truncate_identifier, check_identifier

logger = logging.getLogger(__name__)

IDENTIFIER_MAX_LENGTH = 50
VALID_ATTRIBUTE_CALCULATION_TYPES = [Attribute.TYPE_DECIMAL, Attribute.TYPE_INTEGER]

PROJECT_SIZE = "kokoluokka"
PROJECT_PHASE = "syöttövaihe"

DEFAULT_SHEET_NAME = "Hanketiedot (työversio)"

ATTRIBUTE_NAME = "hanketieto"
ATTRIBUTE_IDENTIFIER = "hanketieto tunniste"
ATTRIBUTE_TYPE = "tietotyyppi"
ATTRIBUTE_CHOICES_SHEET = "vaihtoehtotaulukko"
ATTRIBUTE_UNIT = "mittayksikkö"
ATTRIBUTE_BROADCAST_CHANGES = "tiedon muuttaminen aiheuttaa ilmoituksen shoutboxiin"
ATTRIBUTE_REQUIRED = (
    "pakollinen tieto (jos ei niin kohdan voi valita poistettavaksi)"
)  # kyllä/ei
ATTRIBUTE_PRIORITY = "tiedon sijainti/merkitys käyttäjälle"
ATTRIBUTE_SECTION_PRIORITY = {
    "ensisijainen tieto": 1,
    "automaattinen täyttö": 1,
    "lisätieto": 2,
}

PHASE_SECTION_NAME = "minkä väliotsikon alle kuuluu"
PUBLIC_ATTRIBUTE = "julkinen tieto"  # kyllä/ei julkinen
HELP_TEXT = "ohje"
HELP_LINK = "ohjetta tarkentava linkki"
METADATA_FIELDS = {
    "project_cards": {
        "normal": "normaali hankekortti",
        "extended": "laajennettu hankekortti",
    }
}

CALCULATIONS_COLUMN = "laskelmat"

ATTRIBUTE_FIELDSET = "hanketieto fieldset"

ATTRIBUTE_PHASE_COLUMNS = [
    "syöttövaihe",
    "päivitys-vaihe 2",
    "päivitys-vaihe 3",
    "päivitys-vaihe 4",
]

EXPECTED_A1_VALUE = ATTRIBUTE_NAME

KNOWN_SUBTYPES = ["XS", "S", "M", "L", "XL"]


class Phases(Enum):
    START = "Käynnistys"
    OAS = "OAS"
    PROPOSAL = "Ehdotus"
    REVISED_PROPOSAL = "Tarkistettu ehdotus"
    KHS = "Kanslia-Khs-Valtuusto"
    GOING_INTO_EFFECT = "Voimaantulo"


PROJECT_PHASES = {
    Phases.START.value: {
        "name": Phases.START.value,
        "color": "color--tram",
        "color_code": "#009246",
    },  # None
    # {'name': 'Suunnitteluperiaatteet', 'color': '#009142'},
    Phases.OAS.value: {
        "name": Phases.OAS.value,
        "color": "color--summer",
        "color_code": "#ffc61e",
    },  # 01, 03
    # {'name': 'Luonnos', 'color': '#ffd600'},
    Phases.PROPOSAL.value: {
        "name": Phases.PROPOSAL.value,
        "color": "color--metro",
        "color_code": "#fd4f00",
    },  # 02, 04
    Phases.REVISED_PROPOSAL.value: {
        "name": Phases.REVISED_PROPOSAL.value,
        "color": "color--bus",
        "color_code": "#0000bf",
    },  # 05, 07
    Phases.KHS.value: {
        "name": Phases.KHS.value,
        "color": "color--black",
        "color_code": "#000000",
    },  # 06, 07 <- Kvsto
    Phases.GOING_INTO_EFFECT.value: {
        "name": Phases.GOING_INTO_EFFECT.value,
        "color": "color--white",
        "color_code": "#ffffff",
    },
}

SUBTYPE_PHASES = {
    "XS": [
        Phases.START.value,
        Phases.OAS.value,
        Phases.PROPOSAL.value,
        Phases.REVISED_PROPOSAL.value,
        Phases.GOING_INTO_EFFECT.value,
    ],
    "S": [
        Phases.START.value,
        Phases.OAS.value,
        Phases.PROPOSAL.value,
        Phases.REVISED_PROPOSAL.value,
        Phases.GOING_INTO_EFFECT.value,
    ],
    "M": [
        Phases.START.value,
        Phases.OAS.value,
        Phases.PROPOSAL.value,
        Phases.REVISED_PROPOSAL.value,
        Phases.KHS.value,
        Phases.GOING_INTO_EFFECT.value,
    ],
    "L": [
        Phases.START.value,
        Phases.OAS.value,
        Phases.PROPOSAL.value,
        Phases.REVISED_PROPOSAL.value,
        Phases.KHS.value,
        Phases.GOING_INTO_EFFECT.value,
    ],
    "XL": [
        Phases.START.value,
        Phases.OAS.value,
        Phases.PROPOSAL.value,
        Phases.REVISED_PROPOSAL.value,
        Phases.KHS.value,
        Phases.GOING_INTO_EFFECT.value,
    ],
}

SUBTYPE_PHASE_METADATA = {
    "XS": {
        Phases.START.value: {"default_end_weeks_delta": 8},
        Phases.OAS.value: {"default_end_weeks_delta": 12},
        Phases.PROPOSAL.value: {"default_end_weeks_delta": 24},
        Phases.REVISED_PROPOSAL.value: {"default_end_weeks_delta": 10},
        Phases.GOING_INTO_EFFECT.value: {"default_end_weeks_delta": 6},
    },
    "S": {
        Phases.START.value: {"default_end_weeks_delta": 8},
        Phases.OAS.value: {"default_end_weeks_delta": 12},
        Phases.PROPOSAL.value: {"default_end_weeks_delta": 24},
        Phases.REVISED_PROPOSAL.value: {"default_end_weeks_delta": 10},
        Phases.GOING_INTO_EFFECT.value: {"default_end_weeks_delta": 6},
    },
    "M": {
        Phases.START.value: {"default_end_weeks_delta": 8},
        Phases.OAS.value: {"default_end_weeks_delta": 12},
        Phases.PROPOSAL.value: {"default_end_weeks_delta": 24},
        Phases.REVISED_PROPOSAL.value: {"default_end_weeks_delta": 10},
        Phases.KHS.value: {"default_end_weeks_delta": 12},
        Phases.GOING_INTO_EFFECT.value: {"default_end_weeks_delta": 6},
    },
    "L": {
        Phases.START.value: {"default_end_weeks_delta": 12},
        Phases.OAS.value: {"default_end_weeks_delta": 16},
        Phases.PROPOSAL.value: {"default_end_weeks_delta": 36},
        Phases.REVISED_PROPOSAL.value: {"default_end_weeks_delta": 14},
        Phases.KHS.value: {"default_end_weeks_delta": 12},
        Phases.GOING_INTO_EFFECT.value: {"default_end_weeks_delta": 6},
    },
    "XL": {
        Phases.START.value: {"default_end_weeks_delta": 12},
        Phases.OAS.value: {"default_end_weeks_delta": 16},
        Phases.PROPOSAL.value: {"default_end_weeks_delta": 36},
        Phases.REVISED_PROPOSAL.value: {"default_end_weeks_delta": 14},
        Phases.KHS.value: {"default_end_weeks_delta": 12},
        Phases.GOING_INTO_EFFECT.value: {"default_end_weeks_delta": 6},
    },
}

# projektin vuosi <- tarkistetun ehdotuksen lautakuntapvm

VALUE_TYPES = {
    "fieldset": Attribute.TYPE_FIELDSET,
    "sisältö; nimi": Attribute.TYPE_SHORT_STRING,
    "tunniste; numerotunniste": Attribute.TYPE_SHORT_STRING,
    "tunniste; numero": Attribute.TYPE_DECIMAL,
    "sisältö; teksti": Attribute.TYPE_LONG_STRING,
    "spatiaalinen": Attribute.TYPE_GEOMETRY,
    "sisältö; kuva": Attribute.TYPE_IMAGE,
    "aikataulu ja tehtävät; pvm": Attribute.TYPE_DATE,
    "aikataulu ja tehtävät; teksti": Attribute.TYPE_LONG_STRING,
    "aikataulu ja tehtävät; kyllä/ei/tieto puuttuu": Attribute.TYPE_BOOLEAN,
    "sisältö; laaja teksti": Attribute.TYPE_LONG_STRING,
    "sisältö; vuosiluku": Attribute.TYPE_SHORT_STRING,
    "linkki aineistoon": Attribute.TYPE_LINK,
    "aineisto liitetään Kaavapinoon": Attribute.TYPE_FILE,
    "numero, automaattinen": Attribute.TYPE_DECIMAL,
    "sisältö; vuosilukuja (1...n)": Attribute.TYPE_LONG_STRING,  # TODO Multiple years
    "sisältö; numero": Attribute.TYPE_DECIMAL,
    "sisältö; valitaan kyllä/ei": Attribute.TYPE_BOOLEAN,  # TODO or kyllä/ei/ei asetettu?
    "sisältö; tekstivalikko": Attribute.TYPE_LONG_STRING,  # TODO Choice of values
    "resurssit; valintalista käyttäjä": Attribute.TYPE_USER,
    "resurssit; valintalista": Attribute.TYPE_SHORT_STRING,
    "sisältö; luettelo": Attribute.TYPE_LONG_STRING,  # TODO List of things
    "sisältö; pvm": Attribute.TYPE_DATE,  # TODO Might need to contain multiple dates
    "sisältö; osoite": Attribute.TYPE_LONG_STRING,  # TODO Might need to contain multiple addresses
    "sisältö; kaavanumero(t)": Attribute.TYPE_LONG_STRING,  # TODO List of identifiers
    "talous; teksti": Attribute.TYPE_LONG_STRING,  # TODO List of strings
    "talous; numero (€)": Attribute.TYPE_LONG_STRING,  # TODO Might have multiple values
    "aikataulu ja tehtävät; pvm ja paikka": Attribute.TYPE_LONG_STRING,  # TODO Time and place
    "aikataulu ja tehtävät; vaihe 1…6": Attribute.TYPE_SHORT_STRING,  # TODO Choice
    "sisältö; teksti (automaattinen täyttö?)": Attribute.TYPE_LONG_STRING,
    "sisältö; kyllä/ei/tieto puuttuu": Attribute.TYPE_BOOLEAN,  # TODO Boolean or choice?
}


class AttributeImporterException(Exception):
    pass


class AttributeImporter:
    """Import attributes and project phase sections for asemakaava project type from the given Excel."""

    def __init__(self, options=None):
        self.options = options
        self.workbook = None

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

        return self._rows_for_sheet(sheet)

    def _rows_for_sheet(self, sheet):
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
        predefined_identifier = row[self.column_index[ATTRIBUTE_IDENTIFIER]]
        if predefined_identifier:
            predefined_identifier = predefined_identifier.strip()
            if not check_identifier(predefined_identifier):
                raise ValueError(
                    f"The identifier '{predefined_identifier}' is not a proper slug value"
                )
            return predefined_identifier

        logger.info(
            f"\nCreating identifier for '{row[self.column_index[ATTRIBUTE_NAME]]}'"
        )
        return self._get_identifier_for_value(row[self.column_index[ATTRIBUTE_NAME]])

    def _is_multiple_choice(self, row, value_type):
        if value_type == Attribute.TYPE_FIELDSET:
            return True
        return False

    def _create_attributes(self, rows: Iterable[Sequence[str]]):
        logger.info("\nCreating attributes...")

        existing_attribute_ids = set(
            Attribute.objects.all().values_list("identifier", flat=True)
        )

        imported_attribute_ids = set()
        created_attribute_count = 0
        updated_attribute_count = 0
        created_choices_count = 0
        for row in rows:
            identifier = self._get_attribute_row_identifier(row)

            name = row[self.column_index[ATTRIBUTE_NAME]].strip(" \t:.")

            value_type_string = row[self.column_index[ATTRIBUTE_TYPE]]
            value_type = (
                VALUE_TYPES.get(value_type_string.strip())
                if value_type_string
                else None
            )

            unit = row[self.column_index[ATTRIBUTE_UNIT]] or None

            broadcast_changes = (
                row[self.column_index[ATTRIBUTE_BROADCAST_CHANGES]] == "kyllä"
            )

            multiple_choice = self._is_multiple_choice(row, value_type)

            try:
                help_text = row[self.column_index[HELP_TEXT]].strip()
            except (IndexError, AttributeError):
                help_text = ""

            try:
                help_link = row[self.column_index[HELP_LINK]].strip()
            except (IndexError, AttributeError):
                help_link = None

            is_public = row[self.column_index[PUBLIC_ATTRIBUTE]] == "kyllä"
            is_required = row[self.column_index[ATTRIBUTE_REQUIRED]] == "kyllä"

            if not value_type:
                logger.warning(
                    f'Unidentified value type "{value_type_string}", defaulting to short string'
                )
                value_type = Attribute.TYPE_SHORT_STRING

            generated, calculations = self._get_generated_calculations(row)
            if generated:
                value_type = Attribute.TYPE_DECIMAL

            attribute, created = Attribute.objects.update_or_create(
                identifier=identifier,
                defaults={
                    "name": name,
                    "value_type": value_type,
                    "help_text": help_text,
                    "help_link": help_link,
                    "public": is_public,
                    "required": is_required,
                    "multiple_choice": multiple_choice,
                    "generated": generated,
                    "calculations": calculations,
                    "unit": unit,
                    "broadcast_changes": broadcast_changes,
                },
            )
            if created:
                created_attribute_count += 1
            else:
                updated_attribute_count += 1
            imported_attribute_ids.add(identifier)

            if row[self.column_index[ATTRIBUTE_CHOICES_SHEET]]:
                created_choices_count += self._create_attribute_choices(attribute, row)

            if created:
                logger.info(f"Created {attribute}")

        # Remove any attributes that was not imported
        old_attribute_ids = existing_attribute_ids - imported_attribute_ids
        logger.info(f"Old Attributes: {old_attribute_ids}")
        if old_attribute_ids:
            Attribute.objects.filter(identifier__in=old_attribute_ids).delete()

        return {
            "created": created_attribute_count,
            "updated": updated_attribute_count,
            "deleted": len(old_attribute_ids),
            "choices": created_choices_count,
        }

    def _get_generated_calculations(self, row):
        calculations_string = row[self.column_index[CALCULATIONS_COLUMN]]
        if not calculations_string:
            return False, None

        # Splits the string when a word or +, -, *, / operators is found
        calculations = re.findall(r"([\w]+|[\+\-\*/])+", calculations_string)

        return True, calculations

    def _create_attribute_choices(self, attribute, row) -> int:
        choices_sheet = row[self.column_index[ATTRIBUTE_CHOICES_SHEET]]
        created_choices_count = 0
        if choices_sheet:
            choices_rows = self._rows_for_sheet(self.workbook[choices_sheet])
            choices = list(itertools.chain.from_iterable(choices_rows))

            AttributeValueChoice.objects.filter(attribute=attribute).delete()
            for idx, choice in enumerate(choices):
                identifier = self._get_identifier_for_value(str(choice))
                AttributeValueChoice.objects.create(
                    attribute=attribute, index=idx, value=choice, identifier=identifier
                )
                created_choices_count += 1
        return created_choices_count

    def _create_fieldset_links(self, rows: Iterable[Sequence[str]]):
        logger.info("\nCreating fieldsets...")

        FieldSetAttribute.objects.all().delete()

        if ATTRIBUTE_FIELDSET not in self.column_index:
            logger.warning(f'Fieldset column "{ATTRIBUTE_FIELDSET}" missing: Skipping')
            return

        fieldset_map = defaultdict(list)

        # Map out the link that need to be created
        for row in rows:
            fieldset_attr = row[self.column_index[ATTRIBUTE_FIELDSET]]
            if not fieldset_attr:
                continue

            attr_id = self._get_attribute_row_identifier(row)
            fieldset_map[fieldset_attr].append(attr_id)

        # Create the links
        for source_id in fieldset_map:
            source = Attribute.objects.get(identifier=source_id)

            for index, target_id in enumerate(fieldset_map[source_id], start=1):
                target = Attribute.objects.get(identifier=target_id)
                fsa = FieldSetAttribute.objects.create(
                    attribute_source=source, attribute_target=target, index=index
                )
                logger.info(f"Created {fsa}")

    def _validate_generated_attributes(self):
        """
        Additional validation for attributes which generates their values

        These check can no be done in the model since the attributes in the
        calculations might not exist when the attribute is created, however
        in the importer we want to make sure that the values entered in the
        XLSX file does actually exist as that should be the case at all times.
        """

        generated_attributes = Attribute.objects.filter(generated=True)

        for attribute in generated_attributes:
            calculations = attribute.calculations
            error = False

            calculation_attributes = Attribute.objects.filter(
                identifier__in=attribute.calculation_attribute_identifiers
            )
            if calculation_attributes.count() != len(
                attribute.calculation_attribute_identifiers
            ):
                logger.warning(
                    f"Could not find the attributes given in calculation. "
                    f"({calculation_attributes.count()}/{len(attribute.calculation_attribute_identifiers)})."
                    f"Error in {attribute.identifier} with calculation {calculations}."
                )
                error = True

            if not all(
                attribute.value_type in VALID_ATTRIBUTE_CALCULATION_TYPES
                for attribute in calculation_attributes
            ):
                logger.warning(
                    f"Calculation attributes are not valid number attributes. "
                    f"Error in {attribute.identifier} with calculation {calculations}."
                )
                error = True

            if error:
                raise Exception(f"Could not add attribute {attribute.identifier}")

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

    def _create_sections(self, rows, subtype: ProjectSubtype):
        logger.info("\nReplacing sections...")

        ProjectPhaseSection.objects.filter(phase__project_subtype=subtype).delete()

        for phase in ProjectPhase.objects.filter(project_subtype=subtype):

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
                section = ProjectPhaseSection.objects.create(
                    phase=phase, index=i, name=phase_section_name
                )
                logger.info(f"Created {section}")

    def _create_attribute_section_links(self, rows, subtype: ProjectSubtype):
        logger.info("\nReplacing attribute section links...")

        ProjectPhaseSectionAttribute.objects.filter(
            section__phase__project_subtype=subtype
        ).delete()

        for phase in ProjectPhase.objects.filter(project_subtype=subtype):

            # Index for attribute within a phase section
            counter = Counter()

            for row in rows:
                project_size = row[self.column_index[PROJECT_SIZE]]
                row_subtypes = self.get_subtypes_from_cell(project_size)
                priority = self._get_section_attribute_priority(row)

                # Filter out attributes that should not be included in the project sub type (size)
                if (
                    "kaikki" not in row_subtypes
                    and subtype.name.lower() not in row_subtypes
                ):
                    continue

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
                    attribute=attribute,
                    section=section,
                    index=counter[section],
                    priority=priority,
                )

                counter[section] += 1

                logger.info(
                    f"Created "
                    f"{section_attribute.section.phase} / "
                    f"{section_attribute.section} / "
                    f"{section_attribute.index} / "
                    f"{section_attribute.attribute}"
                )

    def _get_section_attribute_priority(self, row):
        priority_string = row[self.column_index[ATTRIBUTE_PRIORITY]]
        return ATTRIBUTE_SECTION_PRIORITY.get(priority_string, 1)

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

    def get_subtypes_from_cell(self, cell_content: Optional[str]) -> List[str]:
        # If the subtype is missing we assume it is to be included in all subtypes
        if not cell_content:
            return ["kaikki"]

        if "," in cell_content:
            # Split names and remove whitespace
            return [name.strip().lower() for name in cell_content.split(",")]
        else:
            # Always handle a list
            return [cell_content.lower()]

    def create_phases(self, subtype: ProjectSubtype):
        logger.info(f"\nCreating phases for {subtype.name}...")
        phase_names = SUBTYPE_PHASES[subtype.name.upper()]

        created_phase_count = 0
        updated_phase_count = 0
        old_phases = [obj.id for obj in subtype.phases.order_by("index")]
        for i, phase_name in enumerate(phase_names, start=1):
            phase = PROJECT_PHASES[phase_name]
            metadata = SUBTYPE_PHASE_METADATA[subtype.name.upper()][phase_name]
            project_phase, created = ProjectPhase.objects.update_or_create(
                name=phase["name"],
                project_subtype=subtype,
                defaults={
                    "index": i,
                    "color": phase["color"],
                    "color_code": phase["color_code"],
                    "metadata": metadata,
                },
            )
            if project_phase.id in old_phases:
                old_phases.remove(project_phase.id)

            if created:
                created_phase_count += 1
            else:
                updated_phase_count += 1

        try:
            ProjectPhase.objects.filter(id__in=old_phases).delete()
        except ProtectedError:
            # TODO: Handle removal of Phases when they are in use by Projects
            #       could for instance be disabled by new projects but visible
            #       for old ones.
            pass

        return {
            "created": created_phase_count,
            "updated": updated_phase_count,
            "deleted": len(old_phases),
        }

    def create_subtypes(
        self, rows: Iterable[Sequence[str]]
    ) -> Iterable[ProjectSubtype]:

        subtype_names = [
            subtype.name.lower() for subtype in ProjectSubtype.objects.all()
        ]
        for row in rows:
            subtypes_cell_content = row[self.column_index[PROJECT_SIZE]]
            row_subtypes = self.get_subtypes_from_cell(subtypes_cell_content)

            # If all ("kaikki") of the subtypes are included, continue
            if "kaikki" in row_subtypes:
                continue

            for subtype_name in row_subtypes:
                # Skip non-single word and existing subtypes
                if " " in subtype_name or subtype_name in subtype_names:
                    continue

                subtype_names.append(subtype_name)

        # Sort subtypes by "clothing sizes"
        sort_order = ["xxs", "xs", "s", "m", "l", "xl", "xxl"]
        # Note that if a value is not in the sort order list, it will be ordered first in the list
        ordered_subtype_names = sorted(
            subtype_names,
            key=lambda x: next((i for i, t in enumerate(sort_order) if x == t), 0),
        )

        # Create subtypes
        ordered_subtypes = []
        for index, subtype_name in enumerate(ordered_subtype_names):
            project_subtype, created = ProjectSubtype.objects.update_or_create(
                project_type=self.project_type,
                name=subtype_name.upper(),
                defaults={"index": index},
            )
            ordered_subtypes.append(project_subtype)

        return ordered_subtypes

    @transaction.atomic
    def run(self):
        self.project_type, _ = ProjectType.objects.get_or_create(name="asemakaava")

        filename = self.options.get("filename")
        logger.info(
            f"Importing attributes from file {filename} for project type {self.project_type}..."
        )

        self.workbook = self._open_workbook(filename)
        rows = self._extract_data_from_workbook(self.workbook)

        header_row = rows[0]
        self._set_row_indexes(header_row)

        data_rows = list(filter(self._check_if_row_valid, rows[1:]))

        subtypes = self.create_subtypes(data_rows)
        phase_info = {"created": 0, "updated": 0, "deleted": 0}
        for subtype in subtypes:
            _phase_info = self.create_phases(subtype)
            phase_info["created"] += _phase_info["created"]
            phase_info["updated"] += _phase_info["updated"]
            phase_info["deleted"] += _phase_info["deleted"]
        attribute_info = self._create_attributes(data_rows)
        self._create_fieldset_links(data_rows)
        self._validate_generated_attributes()

        # Remove all attributes from further processing that were part of a fieldset
        data_rows = list(filterfalse(self._row_part_of_fieldset, data_rows))

        for subtype in subtypes:
            self._create_sections(data_rows, subtype)
            self._create_attribute_section_links(data_rows, subtype)
        self._update_type_metadata(data_rows)

        logger.info("Project subtypes {}".format(ProjectSubtype.objects.count()))
        logger.info("Phases {}".format(ProjectPhase.objects.count()))
        logger.info(f"  Created: {phase_info['created']}")
        logger.info(f"  Updated: {phase_info['updated']}")
        logger.info(f"  Deleted: {phase_info['deleted']}")
        logger.info("Attributes {}".format(Attribute.objects.count()))
        logger.info(f"  Created: {attribute_info['created']}")
        logger.info(f"  Updated: {attribute_info['updated']}")
        logger.info(f"  Deleted: {attribute_info['deleted']}")
        logger.info(f"  Choices: {attribute_info['choices']}")
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
