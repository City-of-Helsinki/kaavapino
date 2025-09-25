from django.core.management.base import BaseCommand, CommandError

from projects.importing import DeadlineImporter, DeadlineImporterException
from auditlog.context import disable_auditlog

class Command(BaseCommand):
    help = "Import deadlines from Excel file"

    def __init__(self):
        super().__init__()

    def add_arguments(self, parser):
        parser.add_argument("filename", type=str)
        parser.add_argument("--kv", nargs="?", default="1.1", type=str)

    def handle(self, *args, **options):
        deadline_importer = DeadlineImporter(options)
        try:
            with disable_auditlog():
                deadline_importer.run()
        except DeadlineImporterException as e:
            raise CommandError(e)
