from django.core.management.base import BaseCommand, CommandError
from django.core.serializers.json import json
from django.db import transaction

from projects.models import Project


class Command(BaseCommand):
    help = "Clear all existing deadlines from one or all projects"

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
            with transaction.atomic():
                cleared_attributes = {
                    project_dl.deadline.attribute.identifier: None
                    for project_dl in project.deadlines.all()
                    if project_dl.deadline.attribute
                }
                project.update_attribute_data(cleared_attributes)
                for key, val in cleared_attributes.items():
                    old_value = json.loads(json.dumps(
                        project.attribute_data.get(key),
                        default=str,
                    ))
                    new_value = json.loads(json.dumps(val, default=str))

                    if old_value != new_value:
                        action.send(
                            user=project.user,
                            verb=verbs.UPDATED_ATTRIBUTE,
                            action_object=deadline.attribute,
                            target=self,
                            attribute_identifier=deadline.attribute.identifier,
                            old_value=old_value,
                            new_value=new_value,
                        )

                project.deadlines.all().delete()
