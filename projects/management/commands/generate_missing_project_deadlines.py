from actstream import action
from django.core.management.base import BaseCommand, CommandError
from django.core.serializers.json import json

from projects.actions import verbs
from projects.models import Project, ProjectDeadline


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
            old_deadlines = project.deadlines.all()

            project.update_deadlines()

            updated_deadlines = old_deadlines.union(project.deadlines.all())
            for dl in updated_deadlines:
                try:
                    new_date = project.deadlines.get(deadline=dl.deadline).date
                except ProjectDeadline.DoesNotExist:
                    new_date = None

                try:
                    old_date = old_deadlines.get(deadline=dl.deadline).date
                except ProjectDeadline.DoesNotExist:
                    old_date = None

                old_value = json.loads(json.dumps(old_date, default=str))
                new_value = json.loads(json.dumps(new_date, default=str))

                if old_value != new_value:
                    action.send(
                        project.user,
                        verb=verbs.UPDATED_DEADLINE,
                        action_object=dl.deadline,
                        target=project,
                        deadline_abbreviation=dl.deadline.abbreviation,
                        old_value=old_value,
                        new_value=new_value,
                    )
