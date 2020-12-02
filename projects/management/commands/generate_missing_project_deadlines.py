from django.core.management.base import BaseCommand, CommandError

from projects.models import Project


class Command(BaseCommand):
    help = "Generate missing project schedules for one or all projects"

    def add_arguments(self, parser):
        parser.add_argument("--id", nargs="?", type=int)

    def handle(self, *args, **options):
        project_id = options.get("id")

        if project_id:
            try:
                projects = [Project.objects.get(pk=project_id)]
            except Project.DoesNotExist:
                projects = Project.objects.all()
        else:
            projects = Project.objects.all()

        for project in projects:
            project.update_deadlines()
