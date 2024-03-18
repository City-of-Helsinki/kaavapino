import logging

from django.core.management.base import BaseCommand
from projects.models import Project, ProjectAttributeFile
from django.utils import timezone

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Repair ProjectAttributeFile data for selected project"

    def add_arguments(self, parser):
        parser.add_argument("--id", nargs="?", type=int)

    def handle(self, *args, **options):
        project_id = options.get("id")

        if not project_id:
            return

        project = Project.objects.get(id=project_id)
        logging.info(f'Repairing ProjectAttributeFile data for project {project}')

        attribute_files = ProjectAttributeFile.objects.filter(project=project, archived_at=None)
        logging.info(f'Checking {len(attribute_files)} attribute files')

        mark_as_archived = []
        project_attribute_data = project.attribute_data
        for attribute_file in attribute_files:
            if not attribute_file.fieldset_path_str:
                continue

            fieldset_path_str = attribute_file.fieldset_path_str

            fieldset_attribute_identifier = fieldset_path_str.split("[")[0]
            fieldset_index = fieldset_path_str.split("[")[1].split("]")[0]
            attribute_identifier = fieldset_path_str.split("].")[1]

            fieldset_data = project_attribute_data.get(fieldset_attribute_identifier, None)
            data = fieldset_data[int(fieldset_index)]

            if not data:
                continue

            if data["_deleted"] is True:
                mark_as_archived.append(attribute_file)

        now = timezone.now()
        for attribute_file in mark_as_archived:
            attribute_file.archived_at = now
            attribute_file.save()
            print(f'ProjectAttributeFile {attribute_file} set as archived')