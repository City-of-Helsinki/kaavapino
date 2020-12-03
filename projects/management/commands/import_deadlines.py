from django.core.management.base import BaseCommand, CommandError

from projects.importing import DeadlineImporter, DeadlineImporterException


class Command(BaseCommand):
    help = "Import deadlines from Excel file"

    def __init__(self):
        super().__init__()

    def add_arguments(self, parser):
        parser.add_argument("filename", type=str)

    def handle(self, *args, **options):
        attribute_importer = DeadlineImporter(options)
        try:
            attribute_importer.run()
        except DeadlineImporterException as e:
            raise CommandError(e)
