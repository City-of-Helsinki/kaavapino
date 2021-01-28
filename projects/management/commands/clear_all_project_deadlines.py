from actstream import action
from django.core.management.base import BaseCommand, CommandError
from django.core.serializers.json import json
from django.db import transaction

from projects.models import Project, Deadline
from projects.actions import verbs


class Command(BaseCommand):
    help = "Clear all existing deadlines from one or all projects"

    def add_arguments(self, parser):
        parser.add_argument("--id", nargs="?", type=int)
        parser.add_argument(
            "--overwrite_all", nargs="?", type=bool,
            help="Overwrite all deadline-related attribute_data entries, even if the deadline is not included in the current subtype"
        )

    def handle(self, *args, **options):
        project_id = options.get("id")
        overwrite_all = options.get("overwrite_all")

        if project_id:
            try:
                projects = [Project.objects.get(pk=project_id)]
            except Project.DoesNotExist:
                projects = Project.objects.all()
        else:
            projects = Project.objects.all()

        for project in projects:
            with transaction.atomic():
                if overwrite_all:
                    cleared_attributes = [
                        deadline.attribute
                        for deadline in Deadline.objects.all()
                        if deadline.attribute and \
                            project.attribute_data.get(deadline.attribute.identifier)
                    ]
                else:
                    cleared_attributes = [
                        project_dl.deadline.attribute
                        for project_dl in project.deadlines.all()
                        if project_dl.deadline.attribute
                    ]

                project.update_attribute_data({
                    attr.identifier: None
                    for attr in cleared_attributes
                })
                project.save()

                for attribute in cleared_attributes:
                    old_value = json.loads(json.dumps(
                        project.attribute_data.get(attribute.identifier),
                        default=str,
                    ))
                    new_value = None

                    if old_value != new_value:
                        action.send(
                            project.user,
                            verb=verbs.UPDATED_ATTRIBUTE,
                            action_object=attribute,
                            target=project,
                            attribute_identifier=attribute.identifier,
                            old_value=old_value,
                            new_value=new_value,
                        )

                project.deadlines.all().delete()
