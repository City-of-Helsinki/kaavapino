import logging
from collections import Counter, OrderedDict

from openpyxl import load_workbook

from projects.models import ProjectPhaseSection, ProjectPhaseSectionAttribute

from ..models import Attribute, ProjectPhase, ProjectType
from ..models.utils import create_identifier

logger = logging.getLogger(__name__)

EXPECTED_A1_VALUE = 'HANKETIETO'
DEFAULT_SHEET_NAME = 'Taul2'

SECTION_COLUMNS = [4, 5, 6]

PROJECT_PHASES = [
    {'name': 'Käynnistys', 'color': 'color--tram'},
    # {'name': 'Suunnitteluperiaatteet', 'color': '#009142'},
    {'name': 'OAS', 'color': 'color--summer'},
    # {'name': 'Luonnos', 'color': '#ffd600'},
    {'name': 'Ehdotus', 'color': 'color--metro'},
    {'name': 'Tarkistettu ehdotus', 'color': 'color--bus'},
    {'name': 'Kanslia-Khs-Valtuusto', 'color': 'color--black'},
    {'name': 'Voimaantulo', 'color': 'color--white'}
]

VALUE_TYPES = {
    'tunniste; numerotunniste': Attribute.TYPE_SHORT_STRING,
    'sisältö; nimi': Attribute.TYPE_SHORT_STRING,
    'sisältö; valitaan toinen': Attribute.TYPE_BOOLEAN,
    'sisältö; teksti': Attribute.TYPE_LONG_STRING,
    'aikataulu ja tehtävät; kyllä/ei': Attribute.TYPE_BOOLEAN,
    'aikataulu ja tehtävät; valitaan toinen': Attribute.TYPE_SHORT_STRING,
    'aikataulu ja tehtävät; pvm': Attribute.TYPE_DATE,
    'sisältö; numero': Attribute.TYPE_INTEGER,
}


class AttributeImporterException(Exception):
    pass


class AttributeImporter:
    def __init__(self, options=None):
        self.options = options

    def _open_workbook(self, filename):
        try:
            return load_workbook(filename, read_only=True)
        except FileNotFoundError as e:
            raise AttributeImporterException(e)

    def _extract_data_from_workbook(self, workbook):
        try:
            sheet = workbook.get_sheet_by_name(self.options.get('sheet') or DEFAULT_SHEET_NAME)
        except KeyError as e:
            raise AttributeImporterException(e)

        if sheet['A1'].value != EXPECTED_A1_VALUE:
            raise AttributeImporterException('This does not seem to be a valid attribute sheet.')

        data = []

        for row in sheet.iter_rows():
            if not row[0].value:
                break
            data.append([col.value for col in row])

        return data

    def _get_datum_identifier(self, row):
        return create_identifier(row[0].strip(' \t:.'))

    def _update_attributes(self, data):
        logger.info('\nUpdating attributes...')

        for datum in data[1:]:
            identifier = self._get_datum_identifier(datum)

            name = datum[0].strip(' \t:.')
            value_type = VALUE_TYPES.get(datum[3].strip())

            if not value_type:
                logger.warning('Unidentified value type "{}", defaulting to short string'.format(datum[3]))
                value_type = Attribute.TYPE_SHORT_STRING

            overwrite = self.options.get('overwrite')

            if overwrite:
                method = Attribute.objects.update_or_create
            else:
                method = Attribute.objects.get_or_create

            attribute, created = method(identifier=identifier, defaults=({
                'name': name,
                'value_type': value_type,
            }))

            if created:
                action_str = 'Created'
            else:
                action_str = 'Updated' if overwrite else 'Already exists, skipping'

            logger.info('{} {}'.format(action_str, attribute))

    def _update_sections(self, data):
        logger.info('\nUpdating sections...')

        for phase_num in [0, 1, 2]:
            phase = ProjectPhase.objects.get(project_type=self.project_type, index=phase_num)

            # Get all distinct section names in appearance order
            phase_sections = []
            for datum in data[1:]:
                section_name = datum[SECTION_COLUMNS[phase_num]]

                if not section_name or not isinstance(section_name, str):
                    continue

                section_name = section_name.strip()

                if section_name and section_name not in phase_sections:
                    phase_sections.append(section_name)

            for idx, phase_section_name in enumerate(phase_sections):
                overwrite = self.options.get('overwrite')

                if overwrite:
                    method = ProjectPhaseSection.objects.update_or_create
                else:
                    method = ProjectPhaseSection.objects.get_or_create

                section, created = method(phase=phase, index=idx, defaults=({
                    'name': phase_section_name,
                }))

                if created:
                    action_str = 'Created'
                else:
                    action_str = 'Updated' if overwrite else 'Already exists, skipping'

                logger.info('{} {}'.format(action_str, section))

    def _replace_attribute_section_links(self, data):
        logger.info('\nReplacing attribute section links...')

        ProjectPhaseSectionAttribute.objects.filter(section__phase__project_type=self.project_type).delete()

        counter = Counter()
        for datum in data[1:]:
            identifier = self._get_datum_identifier(datum)
            try:
                attribute = Attribute.objects.get(identifier=identifier)
            except Attribute.DoesNotExist:
                logger.warning('Attribute "{}" does not exist.'.format(identifier))
                continue

            for phase_num in [0, 1, 2]:
                phase = ProjectPhase.objects.get(project_type=self.project_type, index=phase_num)

                section_name = datum[SECTION_COLUMNS[phase_num]]
                if not section_name or not isinstance(section_name, str):
                    # Attribute doesn't appear in this phase
                    continue

                section_name = section_name.strip()
                try:
                    section = ProjectPhaseSection.objects.get(phase=phase, name=section_name)
                except ProjectPhaseSection.DoesNotExist:
                    logger.warning('Section "{}" in phase {} does not exist.'.format(section_name, phase))

                is_generated = False

                master_data_description = datum[1].strip()
                if 'muodostuu' in master_data_description and 'perusteella' in master_data_description:
                    is_generated = True

                is_required = True

                ProjectPhaseSectionAttribute.objects.create(
                    attribute=attribute,
                    section=section,
                    generated=is_generated,
                    required=is_required,
                    index=counter[section],
                )

                counter[section] += 1

    def create_phases(self):
        logger.info('\nCreating phases...')
        current_phases = [obj.name for obj in self.project_type.phases.order_by('index')]
        new_phases = [x['name'] for x in PROJECT_PHASES]
        if current_phases == new_phases:
            return

        self.project_type.phases.all().delete()
        for idx, phase in enumerate(PROJECT_PHASES):
            ProjectPhase.objects.create(
                project_type=self.project_type, name=phase['name'], index=idx, color=phase['color']
            )

    def run(self):
        self.project_type, _ = ProjectType.objects.get_or_create(name='asemakaava')

        filename = self.options.get('filename')
        logger.info('Importing attributes from file {} for project type {}...'.format(filename, self.project_type))

        self.create_phases()

        workbook = self._open_workbook(filename)
        data = self._extract_data_from_workbook(workbook)
        self._update_attributes(data)
        self._update_sections(data)
        self._replace_attribute_section_links(data)

        logger.info('Import done.')
