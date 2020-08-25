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
    ProjectFloorAreaSection,
    ProjectFloorAreaSectionAttribute,
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

PROJECT_SIZE = "prosessin kokoluokka, joissa kenttä näkyy"

DEFAULT_SHEET_NAME = "Kaavaprojektitiedot"
CHOICES_SHEET_NAME = "Pudotusvalikot"

ATTRIBUTE_NAME = "projektitieto"
ATTRIBUTE_IDENTIFIER = "projektitieto tunniste"
ATTRIBUTE_TYPE = "kenttätyyppi"
ATTRIBUTE_CHOICES_REF = "pudotusvalikko/vaihtoehdot"
ATTRIBUTE_UNIT = "mittayksikkö"
ATTRIBUTE_BROADCAST_CHANGES = "muutos näkyy viestit-ikkunassa"
ATTRIBUTE_REQUIRED = "pakollinen tieto"  # kyllä/ei
ATTRIBUTE_MULTIPLE_CHOICE = "tietoa voi olla useita" # kyllä/ei

PHASE_SECTION_NAME = "tietoryhmä"
PUBLIC_ATTRIBUTE = "tiedon julkisuus"  # kyllä/ei julkinen
HELP_TEXT = "ohje tiedon syöttäjälle"
HELP_LINK = "ohjeeseen liittyvä linkki"

CALCULATIONS_COLUMN = "laskelmat"

ATTRIBUTE_FIELDSET = "projektitieto fieldset"

ATTRIBUTE_PHASE_COLUMNS = [
    "käynnistysvaiheen  otsikot ja kenttien järjestys tietojen muokkaus -näkymässä ",
    "periaatteet -vaiheen  otsikot ja kenttien järjestys tietojen muokkaus -näkymässä ",
    "oas-vaiheen  otsikot ja kenttien järjestys tietojen muokkaus -näkymässä ",
    "luonnosvaiheen  otsikot ja kenttien järjestys tietojen muokkaus -näkymässä ",
    " ehdotusvaiheen otsikot ja kenttien järjestys tietojen muokkaus -näkymässä ",
    "tarkistettu ehdotus -vaiheen  otsikot ja kenttien järjestys tietojen muokkaus -näkymässä ",
    "hyväksymisvaiheen otsikot ja kenttien järjestys tietojen muokkaus -näkymässä ",
    "voimaantulovaiheen  otsikot ja kenttien järjestys tietojen muokkaus -näkymässä ",
]

ATTRIBUTE_FLOOR_AREA_SECTION = "kerrosalatietojen muokkaus -näkymän osiot"

EXPECTED_A1_VALUE = ATTRIBUTE_NAME

KNOWN_SUBTYPES = ["XS", "S", "M", "L", "XL"]


class Phases(Enum):
    START = "Käynnistys"
    PRINCIPLES = "Suunnitteluperiaatteet"
    OAS = "OAS"
    DRAFT = "Luonnos"
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
    Phases.PRINCIPLES.value: {
        "name": Phases.PRINCIPLES.value,
        "color": '#009142',
    },
    Phases.OAS.value: {
        "name": Phases.OAS.value,
        "color": "color--summer",
        "color_code": "#ffc61e",
    },  # 01, 03
    Phases.DRAFT.value: {
        "name": Phases.DRAFT.value,
        "color": '#ffd600',
    },
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

VALUE_TYPES = {
    "AD-tunnukset": Attribute.TYPE_USER,
    "automaatinen (teksti), kun valitaan henkilö": Attribute.TYPE_SHORT_STRING,
    "automaattinen (desimaaliluku), tieto tulee kaavan tietomallista": Attribute.TYPE_DECIMAL,
    "automaattinen (kokonaisluku), jonka Kaavapino laskee": Attribute.TYPE_INTEGER,
    "automaattinen (kokonaisluku), kun projekti luodaan": Attribute.TYPE_INTEGER,
    "automaattinen (kokonaisluku), kun projekti luodaan, kokonaisluku": Attribute.TYPE_INTEGER,
    "automaattinen (kokonaisluku), tieto tulee Factasta": Attribute.TYPE_INTEGER,
    "automaattinen (kokonaisluku), tieto tulee kaavan tietomallista": Attribute.TYPE_INTEGER,
    "automaattinen (pvm)": Attribute.TYPE_DATE,
    "automaattinen (pvm), mutta päivämäärää voi muuttaa": Attribute.TYPE_DATE,
    "automaattinen (spatiaalinen), tieto tulee kaavan tietomallista": Attribute.TYPE_GEOMETRY,
    "automaattinen (teksti), jonka Kaavapino muodostaa": Attribute.TYPE_LONG_STRING,
    "automaattinen (teksti), kun projekti luodaan": Attribute.TYPE_LONG_STRING,
    "automaattinen (teksti), kun valitaan vastuuyksikkö": Attribute.TYPE_LONG_STRING,
    "automaattinen (teksti), tieto tulee Factasta": Attribute.TYPE_LONG_STRING,
    "automaattinen (valinta)": Attribute.TYPE_LONG_STRING,
    "automaattinen (valinta), kun projekti luodaan": Attribute.TYPE_LONG_STRING,
    "Desimaaliluvun syöttö": Attribute.TYPE_DECIMAL,
    "fieldset": Attribute.TYPE_FIELDSET,
    "Kokonaisluvun syöttö.": Attribute.TYPE_INTEGER,
    "Kuvan lataaminen.": Attribute.TYPE_IMAGE,
    "Kyllä/Ei": Attribute.TYPE_BOOLEAN,
    "Kyllä/Ei/Tieto puuttuu": Attribute.TYPE_BOOLEAN,
    "Linkin liittäminen.": Attribute.TYPE_LINK,
    "Lyhyen tekstin syöttö.": Attribute.TYPE_RICH_TEXT_SHORT,
    "Numerosarjan syöttö.": Attribute.TYPE_SHORT_STRING,
    "Pitkän tekstin syöttö.": Attribute.TYPE_RICH_TEXT,
    "Päivämäärän valinta.": Attribute.TYPE_DATE,
    "Valinta (1) pudotusvalikosta.": Attribute.TYPE_CHOICE,
    "Valinta (1) valintapainikkeesta.": Attribute.TYPE_CHOICE,
    "Valinta (1-2) painikkeesta.": Attribute.TYPE_CHOICE,
    "Valinta (1-x) pudotusvalikosta.": Attribute.TYPE_CHOICE,
    "Valintaruutu.": Attribute.TYPE_BOOLEAN,
}

DISPLAY_TYPES = {
    "Valinta (1) pudotusvalikosta.": Attribute.DISPLAY_DROPDOWN,
    "Valinta (1-x) pudotusvalikosta.": Attribute.DISPLAY_DROPDOWN,
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

        return self._rows_for_sheet(sheet, 1)

    def _rows_for_sheet(self, sheet, start=0):
        data = []

        for row in list(sheet.iter_rows())[start:]:
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
            display = (
                DISPLAY_TYPES.get(value_type_string.strip(), None)
                if value_type_string
                else None
            )
            unit = row[self.column_index[ATTRIBUTE_UNIT]] or None

            broadcast_changes = (
                row[self.column_index[ATTRIBUTE_BROADCAST_CHANGES]] == "kyllä"
            )

            multiple_choice = row[self.column_index[ATTRIBUTE_MULTIPLE_CHOICE]] == "kyllä"

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
                    "display": display,
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

            choices_ref = row[self.column_index[ATTRIBUTE_CHOICES_REF]]
            if choices_ref:
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
        if calculations_string in [None, 'ei']:
            return False, None

        # Splits the string when a word or +, -, *, / operators is found
        calculations = re.findall(r"([\w]+|[\+\-\*/])+", calculations_string)

        return True, calculations

    def _create_attribute_choices(self, attribute, row) -> int:
        created_choices_count = 0
        choices_rows = self._rows_for_sheet(self.workbook[CHOICES_SHEET_NAME])
        choices_ref = row[self.column_index[ATTRIBUTE_CHOICES_REF]]

        try:
            column_index = choices_rows[0].index(choices_ref)
        except ValueError:
            choices_rows = choices_ref.split("/")
            column_index = -1

        for index, choice_row in enumerate(choices_rows):
            if column_index < 0:
                choice = choice_row
            elif index == 0:
                continue
            else:
                choice = choice_row[column_index]

            identifier = self._get_identifier_for_value(str(choice))
            if not choice:
                break

            _, created = AttributeValueChoice.objects.update_or_create(
                attribute=attribute,
                index=index,
                value=choice,
                identifier=identifier
            )

            if created:
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

        for index, column_name in enumerate(ATTRIBUTE_PHASE_COLUMNS):
            value = row[self.column_index[column_name]]
            if value in [None, "ei"]:
                continue

            try:
                value = index
                input_phases.append(index)
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

    def _create_floor_area_sections(self, rows, subtype: ProjectSubtype):
        logger.info("\nReplacing floor area sections...")

        ProjectFloorAreaSection.objects \
            .filter(project_subtype=subtype).delete()

        # Get all distinct section names in appearance order
        subtype_sections = []

        for row in rows:
            try:
                section_name = \
                    row[self.column_index[ATTRIBUTE_FLOOR_AREA_SECTION]].strip()
            except AttributeError:
                continue

            if section_name != "ei" and section_name not in subtype_sections:
                subtype_sections.append(section_name)

        for i, section_name in enumerate(subtype_sections, start=1):
            section = ProjectFloorAreaSection.objects.create(
                project_subtype=subtype, index=i, name=section_name
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
                )

                counter[section] += 1

                logger.info(
                    f"Created "
                    f"{section_attribute.section.phase} / "
                    f"{section_attribute.section} / "
                    f"{section_attribute.index} / "
                    f"{section_attribute.attribute}"
                )

    def _create_floor_area_attribute_section_links(
        self, rows, subtype: ProjectSubtype
    ):
        logger.info("\nReplacing attribute floor area section links...")

        ProjectFloorAreaSectionAttribute.objects.filter(
            section__project_subtype=subtype
        ).delete()

        # Index for attribute within a phase section
        counter = Counter()

        for row in rows:
            project_size = row[self.column_index[PROJECT_SIZE]]
            row_subtypes = self.get_subtypes_from_cell(project_size)

            # Filter out attributes that should not be included in the project sub type (size)
            if (
                "kaikki" not in row_subtypes
                and subtype.name.lower() not in row_subtypes
            ):
                continue

            identifier = self._get_attribute_row_identifier(row)
            attribute = Attribute.objects.get(identifier=identifier)

            try:
                section_name = \
                    row[self.column_index[ATTRIBUTE_FLOOR_AREA_SECTION]].strip()
            except AttributeError:
                continue

            if section_name == "ei":
                continue

            section = ProjectFloorAreaSection.objects.get(
                project_subtype=subtype, name=section_name
            )

            section_attribute = ProjectFloorAreaSectionAttribute.objects.create(
                attribute=attribute,
                section=section,
                index=counter[section],
            )

            counter[section] += 1

            logger.info(
                f"Created "
                f"{section_attribute.section.project_subtype} / "
                f"{section_attribute.section} / "
                f"{section_attribute.index} / "
                f"{section_attribute.attribute}"
            )

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

            self._create_floor_area_sections(data_rows, subtype)
            self._create_floor_area_attribute_section_links(data_rows, subtype)

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
