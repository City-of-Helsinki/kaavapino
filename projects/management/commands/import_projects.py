from django.core.management.base import BaseCommand, CommandError

from projects.importing import ProjectImporter, ProjectImporterException


class Command(BaseCommand):
    help = "Import attributes from Excel file"

    def __init__(self):
        super().__init__()

    def add_arguments(self, parser):
        parser.add_argument("filename", type=str)

    def handle(self, *args, **options):
        project_importer = ProjectImporter(options)
        try:
            project_importer.run()
        except ProjectImporterException as e:
            raise CommandError(e)
