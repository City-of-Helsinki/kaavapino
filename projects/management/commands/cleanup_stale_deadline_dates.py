"""
KAAV-3492 Cleanup: Remove stale deadline dates from production projects.

When a deadline group is deleted (visibility bool set to False), the associated 
date fields should be cleared. This command cleans up projects where stale dates
remain from before the KAAV-3492 fix.

ALWAYS run the audit command first:
    poetry run python manage.py audit_stale_deadline_dates

Then run this with --dry-run to preview changes:
    poetry run python manage.py cleanup_stale_deadline_dates --dry-run

Clean specific project:
    poetry run python manage.py cleanup_stale_deadline_dates --id 42 --execute

Finally execute:
    poetry run python manage.py cleanup_stale_deadline_dates --execute
"""
import logging
from django.core.management.base import BaseCommand
from django.db import transaction
from projects.models import Project
from projects.serializers.utils import VIS_BOOL_MAP

logger = logging.getLogger(__name__)


# Map each deadline group to its associated date fields
# These are the fields that should be cleared when the group is deleted
DEADLINE_GROUP_DATE_FIELDS = {
    # Periaatteet esilläolo
    'periaatteet_esillaolokerta_1': [
        'milloin_periaatteet_esillaolo_alkaa',
        'milloin_periaatteet_esillaolo_paattyy',
        'periaatteet_esillaolo_aineiston_maaraaika',
    ],
    'periaatteet_esillaolokerta_2': [
        'milloin_periaatteet_esillaolo_alkaa_2',
        'milloin_periaatteet_esillaolo_paattyy_2',
        'periaatteet_esillaolo_aineiston_maaraaika_2',
    ],
    'periaatteet_esillaolokerta_3': [
        'milloin_periaatteet_esillaolo_alkaa_3',
        'milloin_periaatteet_esillaolo_paattyy_3',
        'periaatteet_esillaolo_aineiston_maaraaika_3',
    ],
    # Periaatteet lautakunta
    'periaatteet_lautakuntakerta_1': [
        'milloin_periaatteet_lautakunnassa',
        'periaatteet_lautakunta_aineiston_maaraaika',
    ],
    'periaatteet_lautakuntakerta_2': [
        'milloin_periaatteet_lautakunnassa_2',
        'periaatteet_lautakunta_aineiston_maaraaika_2',
    ],
    'periaatteet_lautakuntakerta_3': [
        'milloin_periaatteet_lautakunnassa_3',
        'periaatteet_lautakunta_aineiston_maaraaika_3',
    ],
    'periaatteet_lautakuntakerta_4': [
        'milloin_periaatteet_lautakunnassa_4',
        'periaatteet_lautakunta_aineiston_maaraaika_4',
    ],
    # OAS esilläolo
    'oas_esillaolokerta_1': [
        'milloin_oas_esillaolo_alkaa',
        'milloin_oas_esillaolo_paattyy',
        'oas_esillaolo_aineiston_maaraaika',
    ],
    'oas_esillaolokerta_2': [
        'milloin_oas_esillaolo_alkaa_2',
        'milloin_oas_esillaolo_paattyy_2',
        'oas_esillaolo_aineiston_maaraaika_2',
    ],
    'oas_esillaolokerta_3': [
        'milloin_oas_esillaolo_alkaa_3',
        'milloin_oas_esillaolo_paattyy_3',
        'oas_esillaolo_aineiston_maaraaika_3',
    ],
    # Luonnos esilläolo
    'luonnos_esillaolokerta_1': [
        'milloin_luonnos_esillaolo_alkaa',
        'milloin_luonnos_esillaolo_paattyy',
        'kaavaluonnos_esillaolo_aineiston_maaraaika',
    ],
    'luonnos_esillaolokerta_2': [
        'milloin_luonnos_esillaolo_alkaa_2',
        'milloin_luonnos_esillaolo_paattyy_2',
        'kaavaluonnos_esillaolo_aineiston_maaraaika_2',
    ],
    'luonnos_esillaolokerta_3': [
        'milloin_luonnos_esillaolo_alkaa_3',
        'milloin_luonnos_esillaolo_paattyy_3',
        'kaavaluonnos_esillaolo_aineiston_maaraaika_3',
    ],
    # Luonnos lautakunta
    'luonnos_lautakuntakerta_1': [
        'milloin_kaavaluonnos_lautakunnassa',
        'kaavaluonnos_kylk_aineiston_maaraaika',
    ],
    'luonnos_lautakuntakerta_2': [
        'milloin_kaavaluonnos_lautakunnassa_2',
        'kaavaluonnos_kylk_aineiston_maaraaika_2',
    ],
    'luonnos_lautakuntakerta_3': [
        'milloin_kaavaluonnos_lautakunnassa_3',
        'kaavaluonnos_kylk_aineiston_maaraaika_3',
    ],
    'luonnos_lautakuntakerta_4': [
        'milloin_kaavaluonnos_lautakunnassa_4',
        'kaavaluonnos_kylk_aineiston_maaraaika_4',
    ],
    # Ehdotus nähtävilläolo
    'ehdotus_nahtavillaolokerta_1': [
        'milloin_ehdotuksen_nahtavilla_alkaa',
        'milloin_ehdotuksen_nahtavilla_paattyy',
        'ehdotus_nahtaville_aineiston_maaraaika',
    ],
    'ehdotus_nahtavillaolokerta_2': [
        'milloin_ehdotuksen_nahtavilla_alkaa_2',
        'milloin_ehdotuksen_nahtavilla_paattyy_2',
        'ehdotus_nahtaville_aineiston_maaraaika_2',
    ],
    'ehdotus_nahtavillaolokerta_3': [
        'milloin_ehdotuksen_nahtavilla_alkaa_3',
        'milloin_ehdotuksen_nahtavilla_paattyy_3',
        'ehdotus_nahtaville_aineiston_maaraaika_3',
    ],
    'ehdotus_nahtavillaolokerta_4': [
        'milloin_ehdotuksen_nahtavilla_alkaa_4',
        'milloin_ehdotuksen_nahtavilla_paattyy_4',
        'ehdotus_nahtaville_aineiston_maaraaika_4',
    ],
    # Ehdotus lautakunta
    'ehdotus_lautakuntakerta_1': [
        'milloin_kaavaehdotus_lautakunnassa',
        'ehdotus_lautakunta_aineiston_maaraaika',
    ],
    'ehdotus_lautakuntakerta_2': [
        'milloin_kaavaehdotus_lautakunnassa_2',
        'ehdotus_lautakunta_aineiston_maaraaika_2',
    ],
    'ehdotus_lautakuntakerta_3': [
        'milloin_kaavaehdotus_lautakunnassa_3',
        'ehdotus_lautakunta_aineiston_maaraaika_3',
    ],
    'ehdotus_lautakuntakerta_4': [
        'milloin_kaavaehdotus_lautakunnassa_4',
        'ehdotus_lautakunta_aineiston_maaraaika_4',
    ],
    # Tarkistettu ehdotus lautakunta
    'tarkistettu_ehdotus_lautakuntakerta_1': [
        'milloin_tarkistettu_ehdotus_lautakunnassa',
        'tarkistettu_ehdotus_kylk_aineiston_maaraaika',
    ],
    'tarkistettu_ehdotus_lautakuntakerta_2': [
        'milloin_tarkistettu_ehdotus_lautakunnassa_2',
        'tarkistettu_ehdotus_kylk_aineiston_maaraaika_2',
    ],
    'tarkistettu_ehdotus_lautakuntakerta_3': [
        'milloin_tarkistettu_ehdotus_lautakunnassa_3',
        'tarkistettu_ehdotus_kylk_aineiston_maaraaika_3',
    ],
    'tarkistettu_ehdotus_lautakuntakerta_4': [
        'milloin_tarkistettu_ehdotus_lautakunnassa_4',
        'tarkistettu_ehdotus_kylk_aineiston_maaraaika_4',
    ],
}


class Command(BaseCommand):
    help = "Clean up stale deadline dates where visibility bool is False but dates still exist"

    def add_arguments(self, parser):
        parser.add_argument(
            "--id",
            type=int,
            help="Clean only a specific project by ID"
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be cleaned without making changes"
        )
        parser.add_argument(
            "--execute",
            action="store_true",
            help="Actually execute the cleanup (required to make changes)"
        )
        parser.add_argument(
            "--include-archived",
            action="store_true",
            help="Include archived projects in the cleanup"
        )

    def handle(self, *args, **options):
        project_id = options.get("id")
        dry_run = options.get("dry_run", False)
        execute = options.get("execute", False)
        include_archived = options.get("include_archived", False)

        # Require explicit --dry-run or --execute
        if not dry_run and not execute:
            self.stdout.write(self.style.ERROR(
                "\n❌ You must specify either --dry-run or --execute\n"
                "\nUsage:\n"
                "  poetry run python manage.py cleanup_stale_deadline_dates --dry-run\n"
                "  poetry run python manage.py cleanup_stale_deadline_dates --execute\n"
            ))
            return

        # Build queryset
        if project_id:
            projects = Project.objects.filter(pk=project_id)
        else:
            projects = Project.objects.all()
            if not include_archived:
                projects = projects.filter(archived=False)

        mode = "DRY RUN" if dry_run else "EXECUTING"
        self.stdout.write(self.style.NOTICE(
            f"\n{'='*70}\n"
            f"KAAV-3492 Stale Deadline Date Cleanup ({mode})\n"
            f"{'='*70}\n"
        ))

        total_projects = projects.count()
        cleaned_projects = []
        total_cleaned_fields = 0

        for project in projects:
            result = self._clean_project(project, dry_run=dry_run)
            
            if result['cleaned_fields']:
                cleaned_projects.append((project, result))
                total_cleaned_fields += result['cleaned_count']

        # Summary
        self.stdout.write(self.style.NOTICE(
            f"\n{'='*70}\n"
            f"SUMMARY ({mode})\n"
            f"{'='*70}\n"
        ))

        if cleaned_projects:
            action = "Would clean" if dry_run else "Cleaned"
            self.stdout.write(self.style.SUCCESS(
                f"✓ {action} {total_cleaned_fields} fields across {len(cleaned_projects)} projects\n"
            ))
            
            if dry_run:
                self.stdout.write(self.style.NOTICE(
                    f"\nTo apply these changes, run:\n"
                    f"  poetry run python manage.py cleanup_stale_deadline_dates --execute\n"
                ))
        else:
            self.stdout.write(self.style.SUCCESS(
                f"✓ No stale data found in {total_projects} projects - nothing to clean\n"
            ))

    def _clean_project(self, project, dry_run=True):
        """
        Clean stale deadline dates from a project.
        
        Returns dict with 'cleaned_fields' list and 'cleaned_count'.
        """
        cleaned_fields = []
        attr_data = project.attribute_data or {}

        for deadline_group, vis_bool_name in VIS_BOOL_MAP.items():
            # Skip groups without visibility bools
            if vis_bool_name is None:
                continue

            # Get the visibility bool value
            vis_bool_value = attr_data.get(vis_bool_name)

            # Only clean if vis_bool is explicitly False
            if vis_bool_value is not False:
                continue

            # Get date fields for this group
            date_fields = DEADLINE_GROUP_DATE_FIELDS.get(deadline_group, [])
            
            # Find and clear stale dates
            for field in date_fields:
                value = attr_data.get(field)
                if value is not None:
                    cleaned_fields.append({
                        'group': deadline_group,
                        'vis_bool': vis_bool_name,
                        'field': field,
                        'old_value': value,
                    })

        if cleaned_fields:
            self._print_cleanup_info(project, cleaned_fields, dry_run)
            
            if not dry_run:
                self._execute_cleanup(project, cleaned_fields)

        return {
            'cleaned_fields': cleaned_fields,
            'cleaned_count': len(cleaned_fields),
        }

    def _print_cleanup_info(self, project, cleaned_fields, dry_run):
        """Print info about fields being cleaned."""
        action = "Would clean" if dry_run else "Cleaning"
        subtype_name = project.subtype.name if project.subtype else "?"
        
        self.stdout.write(self.style.WARNING(
            f"\n{action} Project #{project.id} \"{project.name}\" ({subtype_name}):"
        ))
        
        for field_info in cleaned_fields:
            self.stdout.write(
                f"   {field_info['field']}: {field_info['old_value']} → null"
            )

    def _execute_cleanup(self, project, cleaned_fields):
        """Actually clean the stale fields from the project."""
        with transaction.atomic():
            attr_data = dict(project.attribute_data or {})
            
            for field_info in cleaned_fields:
                field = field_info['field']
                if field in attr_data:
                    del attr_data[field]
                    logger.info(
                        f"Cleared stale field {field} from project {project.id} "
                        f"(was: {field_info['old_value']})"
                    )
            
            project.attribute_data = attr_data
            project.save(update_fields=['attribute_data'])
            
            logger.info(f"Saved project {project.id} after cleaning {len(cleaned_fields)} stale fields")
