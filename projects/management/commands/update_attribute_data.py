import logging

from django.core.management.base import BaseCommand
from projects.models import Project
from django.db import transaction

logger = logging.getLogger(__name__)

KAAVALUONNOS_LAUTAKUNTAAN = "kaavaluonnos_lautakuntaan_1"
JARJESTETAAN_LUONNOS_ESILLAOLO = "jarjestetaan_luonnos_esillaolo_1"

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

        for project in projects:
            changed = False
            with transaction.atomic():
                if project.subtype.name == "XL" and project.attribute_data.get("luonnos_luotu", None):
                    if project.attribute_data.get(KAAVALUONNOS_LAUTAKUNTAAN, None) is None:
                        project.attribute_data[KAAVALUONNOS_LAUTAKUNTAAN] = True
                        changed = True
                    if project.attribute_data.get(JARJESTETAAN_LUONNOS_ESILLAOLO, None) is None:
                        project.attribute_data[JARJESTETAAN_LUONNOS_ESILLAOLO] = True
                        changed = True
                elif project.subtype.name != "XL" or project.attribute_data.get("luonnos_luotu", False) is False:
                    if project.attribute_data.get(KAAVALUONNOS_LAUTAKUNTAAN, None) is not None:
                        project.attribute_data.pop(KAAVALUONNOS_LAUTAKUNTAAN, None)
                        changed = True
                    if project.attribute_data.get(JARJESTETAAN_LUONNOS_ESILLAOLO, None) is not None:
                        project.attribute_data.pop(JARJESTETAAN_LUONNOS_ESILLAOLO, None)
                        changed = True

                if changed:
                    logger.info(f"Updated attribute_data for project {project.name}")
                    project.save()
