from django.core.management.base import BaseCommand, CommandError

from projects.importing.report import ReportTypeCreator


class Command(BaseCommand):
    help = "Create different report types"

    def __init__(self):
        super().__init__()

    def handle(self, *args, **options):
        report_type_creator = ReportTypeCreator()
        try:
            report_type_creator.run()
        except Exception as e:
            raise CommandError(e)
