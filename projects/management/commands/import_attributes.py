from django.core.management.base import BaseCommand, CommandError

from projects.importing import AttributeImporter, AttributeImporterException


class Command(BaseCommand):
    help = "Import attributes from Excel file"

    def __init__(self):
        super().__init__()

    def add_arguments(self, parser):
        parser.add_argument("filename", type=str)
        parser.add_argument("--sheet", nargs="?", type=str)
        parser.add_argument("--overwrite", action="store_true")

    def handle(self, *args, **options):
        attribute_importer = AttributeImporter(options)
        try:
            attribute_importer.run()
        except AttributeImporterException as e:
            raise CommandError(e)
