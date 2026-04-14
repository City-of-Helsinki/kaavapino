import logging

from django.core.management.base import BaseCommand
from projects.models import Project
from django.db import transaction

logger = logging.getLogger(__name__)

XL_ATTRIBUTES = {
    'jarjestetaan_periaatteet_esillaolo_1': True,
    'jarjestetaan_periaatteet_esillaolo_2': False,
    'jarjestetaan_periaatteet_esillaolo_3': False,
    'periaatteet_lautakuntaan_1': True,
    'periaatteet_lautakuntaan_2': False,
    'periaatteet_lautakuntaan_3': False,
    'periaatteet_lautakuntaan_4': False,
    'jarjestetaan_luonnos_esillaolo_1': True,
    'jarjestetaan_luonnos_esillaolo_2': False,
    'jarjestetaan_luonnos_esillaolo_3': False,
    'kaavaluonnos_lautakuntaan_1': True,
    'kaavaluonnos_lautakuntaan_2': False,
    'kaavaluonnos_lautakuntaan_3': False,
    'kaavaluonnos_lautakuntaan_4': False,
    'kaavaehdotus_lautakuntaan_1': True,
    'kaavaehdotus_lautakuntaan_2': False,
    'kaavaehdotus_lautakuntaan_3': False,
    'kaavaehdotus_lautakuntaan_4': False,
}

L_ATTRIBUTES = {
    'kaavaehdotus_lautakuntaan_1': True,
    'kaavaehdotus_lautakuntaan_2': False,
    'kaavaehdotus_lautakuntaan_3': False,
    'kaavaehdotus_lautakuntaan_4': False,
}

COMMON_ATTRIBUTES = {
    'jarjestetaan_oas_esillaolo_1': True,
    'jarjestetaan_oas_esillaolo_2': False,
    'jarjestetaan_oas_esillaolo_3': False,
    'kaavaehdotus_nahtaville_1': True,
    'kaavaehdotus_uudelleen_nahtaville_2': False,
    'kaavaehdotus_uudelleen_nahtaville_3': False,
    'kaavaehdotus_uudelleen_nahtaville_4': False,
    'tarkistettu_ehdotus_lautakuntaan_1': True,
    'tarkistettu_ehdotus_lautakuntaan_2': False,
    'tarkistettu_ehdotus_lautakuntaan_3': False,
    'tarkistettu_ehdotus_lautakuntaan_4': False
}

class Command(BaseCommand):
    help = "Adds default values for missing visibility boolean attributes in existing projects"

    def add_arguments(self, parser):
        parser.add_argument("--id", nargs="?", type=int)

    def handle(self, *args, **options):
        project_id = options.get("id")

        if project_id:
            try:
                projects = [Project.objects.get(pk=project_id)]
            except Project.DoesNotExist:
                projects = Project.objects.filter(archived=False)
        else:
            projects = Project.objects.filter(archived=False)
        with transaction.atomic():
            change_log = []
            changed_project_count = 0
            for project in projects:
                changed = False
                for attribute, default_value in COMMON_ATTRIBUTES.items():
                    if project.attribute_data.get(attribute, None) is None:
                        project.attribute_data[attribute] = default_value
                        changed = True
                        logger.info(f"Set {attribute} to {default_value} for project {project.name}")
                        change_log.append(f"Set {attribute} to {default_value} for project {project.name}")
                if project.subtype.name == "XL":
                    for attribute, default_value in XL_ATTRIBUTES.items():
                        if (not project.create_draft and "luonnos" in attribute) or (not project.create_principles and "periaatteet" in attribute):
                            continue
                        if project.attribute_data.get(attribute, None) is None:
                            project.attribute_data[attribute] = default_value
                            changed = True
                            logger.info(f"Set {attribute} to {default_value} for project {project.name}")
                            change_log.append(f"Set {attribute} to {default_value} for project {project.name}")
                elif project.subtype.name == "L":
                    for attribute, default_value in L_ATTRIBUTES.items():
                        if project.attribute_data.get(attribute, None) is None:
                            project.attribute_data[attribute] = default_value
                            changed = True
                            logger.info(f"Set {attribute} to {default_value} for project {project.name}")
                            change_log.append(f"Set {attribute} to {default_value} for project {project.name}")
                if changed:
                    changed_project_count += 1
                    logger.info(f"Updated attribute_data for project {project.id} {project.name}\n---")
                    change_log.append(f"Updated attribute_data for project {project.id} {project.name}\n---")
                    project.save()
            if (input("Apply changes to database? (y/n): ") or "").lower() != "y":
                raise Exception("Aborting without saving changes to database")

        logger.info(f"Finished updating missing visibility boolean attributes for {changed_project_count} projects")
        if (input("Write changes to file? (y/n): ") or "").lower() == "y":
            try:
                with open("missing_vis_bools_changes.txt", "w") as f:
                    f.write("\n".join(change_log))
                logger.info("Changes written to missing_vis_bools_changes.txt")
            except Exception as e:
                logger.error(f"Failed to write changes to file: {e}")
