import logging

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from projects.models import Project

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
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show planned changes without saving them",
        )
        parser.add_argument(
            "--execute",
            action="store_true",
            help="Apply the changes after confirmation",
        )

    def handle(self, *args, **options):
        project_id = options.get("id")
        dry_run = options.get("dry_run", False)
        execute = options.get("execute", False)

        if dry_run == execute:
            raise CommandError("Specify exactly one of --dry-run or --execute")

        projects = self._get_projects(project_id)
        project_changes, change_log = self._collect_changes(projects)

        self._print_summary(project_changes, dry_run=dry_run)

        if not project_changes:
            logger.info("No missing visibility boolean attributes found")
            return

        if dry_run:
            self._maybe_write_log(change_log)
            return

        if (input("Apply changes to database? (y/n): ") or "").lower() != "y":
            raise CommandError("Aborting without saving changes to database")

        with transaction.atomic():
            for project, changes in project_changes:
                for attribute, default_value in changes:
                    project.attribute_data[attribute] = default_value
                project.save()

        logger.info(
            "Finished updating missing visibility boolean attributes for %s projects",
            len(project_changes),
        )
        self._maybe_write_log(change_log)

    def _get_projects(self, project_id=None):
        if project_id is None:
            return Project.objects.filter(archived=False).select_related("subtype")

        try:
            project = Project.objects.select_related("subtype").get(pk=project_id)
        except Project.DoesNotExist as error:
            raise CommandError(f"Project with id={project_id} does not exist") from error

        return [project]

    def _collect_changes(self, projects):
        project_changes = []
        change_log = []

        for project in projects:
            changes = self._collect_project_changes(project)
            if not changes:
                continue

            project_changes.append((project, changes))
            for attribute, default_value in changes:
                logger.info(
                    "Set %s to %s for project %s",
                    attribute,
                    default_value,
                    project.name,
                )
                change_log.append(
                    f"Set {attribute} to {default_value} for project {project.name}"
                )

            logger.info("Would update attribute_data for project %s %s", project.id, project.name)
            change_log.append(
                f"Updated attribute_data for project {project.id} {project.name}\n---"
            )

        return project_changes, change_log

    def _collect_project_changes(self, project):
        changes = []
        current_values = project.attribute_data

        for attribute, default_value in COMMON_ATTRIBUTES.items():
            if current_values.get(attribute) is None:
                changes.append((attribute, default_value))

        subtype_attributes = {}
        if project.subtype.name == "XL":
            subtype_attributes = XL_ATTRIBUTES
        elif project.subtype.name == "L":
            subtype_attributes = L_ATTRIBUTES

        for attribute, default_value in subtype_attributes.items():
            if (not project.create_draft and "luonnos" in attribute) or (
                not project.create_principles and "periaatteet" in attribute
            ):
                continue
            if current_values.get(attribute) is None:
                changes.append((attribute, default_value))

        return changes

    def _print_summary(self, project_changes, dry_run=False):
        mode = "DRY RUN" if dry_run else "EXECUTE"
        self.stdout.write(self.style.NOTICE(
            f"Running add_missing_vis_bools in {mode} mode"
        ))

        if not project_changes:
            self.stdout.write(self.style.SUCCESS("No projects need updates"))
            return

        self.stdout.write(
            self.style.WARNING(f"Projects to update: {len(project_changes)}")
        )
        for project, changes in project_changes:
            self.stdout.write(f"- {project.id} {project.name}: {len(changes)} changes")
            for attribute, default_value in changes:
                self.stdout.write(f"  {attribute} -> {default_value}")

    def _maybe_write_log(self, change_log):
        if (input("Write changes to file? (y/n): ") or "").lower() != "y":
            return

        try:
            with open("missing_vis_bools_changes.txt", "w") as file_obj:
                file_obj.write("\n".join(change_log))
            logger.info("Changes written to missing_vis_bools_changes.txt")
        except Exception as error:
            logger.error("Failed to write changes to file: %s", error)
