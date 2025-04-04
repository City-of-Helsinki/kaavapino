import logging

from django.core.management.base import BaseCommand
from projects.models import Project, Attribute, FieldSetAttribute
from django.db import transaction

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Update attribute data for V1.1"

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

        placeholders = {attr.identifier: attr.placeholder_text for attr in Attribute.objects.filter(placeholder_text__isnull=False)}

        for project in projects:
            with transaction.atomic():
                updated_attribute_data = {}
                for key, value in placeholders.items():
                    try:
                        FieldSetAttribute.objects.get(attribute_target__identifier=key)
                        # Attribute is a FieldSet attribute
                    except FieldSetAttribute.DoesNotExist:
                        if project.attribute_data.get(key, None) is not None:
                            continue
                        updated_attribute_data[key] = value

                if updated_attribute_data:
                    project.attribute_data.update(updated_attribute_data)
                    project.save()
                    logger.info(f"Updated {len(updated_attribute_data)} placeholder_text values in attribute_data for project {project.name}")
