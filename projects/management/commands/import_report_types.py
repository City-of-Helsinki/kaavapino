from django.core.management.base import BaseCommand, CommandError

from projects.importing import ReportImporter, ReportImporterException


class Command(BaseCommand):
    help = "Import report types from Excel file"

    def __init__(self):
        super().__init__()

    def add_arguments(self, parser):
        parser.add_argument("filename", type=str)

    def handle(self, *args, **options):
        report_type_importer = ReportImporter(options)
        try:
            report_type_importer.run()
        except ReportImporterException as e:
            raise CommandError(e)
