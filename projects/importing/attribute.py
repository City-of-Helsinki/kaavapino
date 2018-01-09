import logging

from openpyxl import load_workbook

from ..models import Attribute, ProjectPhase, ProjectType
from ..models.utils import create_identifier

logger = logging.getLogger(__name__)

EXPECTED_A1_VALUE = 'HANKETIETO'
DEFAULT_SHEET_NAME = 'Taul2'

PROJECT_PHASES = [
    {'name': 'Käynnistys', 'color': '#009142'},
    {'name': 'Suunnitteluperiaatteet', 'color': '#009142'},
    {'name': 'OAS', 'color': '#ffd600'},
    {'name': 'Luonnos', 'color': '#ffd600'},
    {'name': 'Ehdotus', 'color': '#ff4c00'},
    {'name': 'Tarkistettu ehdotus', 'color': '#0100be'},
    {'name': 'Kanslia-Khs-Valtuusto', 'color': '#000000'},
    {'name': 'Voimaantulo', 'color': '#ffffff'}
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

    def _update_models(self, data):
        for datum in data[1:]:
            name = datum[0].strip()
            identifier = create_identifier(name)
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

    def create_phases(self):
        self.project_type, _ = ProjectType.objects.get_or_create(name='asemakaava')
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
        filename = self.options.get('filename')
        logger.info('Importing attributes from file {}...'.format(filename))

        self.create_phases()

        workbook = self._open_workbook(filename)
        data = self._extract_data_from_workbook(workbook)
        self._update_models(data)

        logger.info('Import done.')
