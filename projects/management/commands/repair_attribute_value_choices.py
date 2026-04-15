import logging

from actstream import action
from django.core.management.base import BaseCommand, CommandError
from django.core.serializers.json import json
from django.db import transaction
from six.moves import input

from projects.actions import verbs
from projects.models import Attribute, AttributeValueChoice, Project

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Repair attribute_value_choices in attribute_data for one or all projects"

    def add_arguments(self, parser):
        parser.add_argument("--id", nargs="?", type=int)

    def get_identifier(self, attribute, old_value):
        try:
            new_value = attribute.value_choices.get(legacy_identifier=old_value)
            return new_value.identifier
        except AttributeValueChoice.DoesNotExist:
            return old_value
        except AttributeValueChoice.MultipleObjectsReturned:
            return old_value

    def handle(self, *args, **options):
        project_id = options.get("id")

        if project_id:
            projects = Project.objects.filter(pk=project_id)
        else:
            projects = Project.objects.all()

        if not projects:
            raise CommandError("No projects found")

        attributes = Attribute.objects.filter(value_type=Attribute.TYPE_CHOICE).prefetch_related("value_choices")
        changes = {}

        Project._meta.get_field("modified_at").auto_now = False
        with transaction.atomic():
            for index, project in enumerate(projects):
                print(f'{index+1}/{len(projects)}: {project}')
                changes[project] = []
                for attribute in attributes:
                    if attribute.value_choices.count() == 0:  # No value choices
                        continue
                    identifier = attribute.identifier
                    old_value = project.attribute_data.get(identifier)
                    if old_value:
                        if isinstance(old_value, list):
                            new_value = []
                            for old_item in old_value:
                                new_value.append(self.get_identifier(attribute, old_item))
                        else:
                            new_value = self.get_identifier(attribute, old_value)

                        if old_value != new_value:
                            changes[project].append(f"{attribute.identifier}:   {old_value}   -->   {new_value}")
                            project.attribute_data[identifier] = new_value

                project.save()

            for project, changes in changes.items():  # Display changes
                if not changes:
                    continue
                print(f'{project}:')
                for change in changes:
                    print(f"  {change}")

            confirm = input(f"Apply changes? yes/no ").lower()

            if confirm != "yes":
                raise CommandError("Aborted")

        transaction.commit()
        Project._meta.get_field("modified_at").auto_now = False