"""
KAAV-3492 Pre-deployment Audit: Detect stale deadline dates in production projects.

When a deadline group is deleted (visibility bool set to False), the associated 
date fields should be cleared. If they weren't (due to bugs), those stale dates 
could cause issues when the group is re-added.

This command identifies projects with such inconsistencies WITHOUT making changes.

Usage:
    poetry run python manage.py audit_stale_deadline_dates
    poetry run python manage.py audit_stale_deadline_dates --id 42
    poetry run python manage.py audit_stale_deadline_dates --include-archived
"""
import logging
from django.core.management.base import BaseCommand
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
    help = "Audit projects for stale deadline dates where visibility bool is False but dates still exist"

    def add_arguments(self, parser):
        parser.add_argument(
            "--id",
            type=int,
            help="Check only a specific project by ID"
        )
        parser.add_argument(
            "--include-archived",
            action="store_true",
            help="Include archived projects in the audit"
        )
        parser.add_argument(
            "--verbose",
            action="store_true",
            help="Show all projects, not just those with issues"
        )

    def handle(self, *args, **options):
        project_id = options.get("id")
        include_archived = options.get("include_archived", False)
        verbose = options.get("verbose", False)

        # Build queryset
        if project_id:
            projects = Project.objects.filter(pk=project_id)
        else:
            projects = Project.objects.all()
            if not include_archived:
                projects = projects.filter(archived=False)

        self.stdout.write(self.style.NOTICE(
            f"\n{'='*70}\n"
            f"KAAV-3492 Stale Deadline Date Audit\n"
            f"{'='*70}\n"
        ))

        total_projects = projects.count()
        affected_projects = []
        total_stale_fields = 0

        for project in projects:
            issues = self._check_project(project)
            
            if issues:
                affected_projects.append((project, issues))
                total_stale_fields += sum(len(fields) for _, _, fields in issues)
                self._print_project_issues(project, issues)
            elif verbose:
                self.stdout.write(self.style.SUCCESS(
                    f"✓ Project #{project.id} \"{project.name}\" ({project.subtype.name}) - No stale data"
                ))

        # Summary
        self.stdout.write(self.style.NOTICE(
            f"\n{'='*70}\n"
            f"SUMMARY\n"
            f"{'='*70}\n"
        ))

        if affected_projects:
            self.stdout.write(self.style.WARNING(
                f"⚠️  {len(affected_projects)} projects with stale data out of {total_projects} total\n"
                f"   Total stale fields: {total_stale_fields}\n"
            ))
            self.stdout.write(self.style.NOTICE(
                f"\nAffected project IDs: {', '.join(str(p.id) for p, _ in affected_projects)}\n"
            ))
            self.stdout.write(self.style.NOTICE(
                f"\nTo fix these issues, run:\n"
                f"  poetry run python manage.py cleanup_stale_deadline_dates --dry-run\n"
                f"  poetry run python manage.py cleanup_stale_deadline_dates --execute\n"
            ))
        else:
            self.stdout.write(self.style.SUCCESS(
                f"✓ No stale data found in {total_projects} projects\n"
            ))

    def _check_project(self, project):
        """
        Check a project for stale deadline dates.
        
        Returns a list of tuples: [(deadline_group, [stale_field_info, ...]), ...]
        """
        issues = []
        attr_data = project.attribute_data or {}

        for deadline_group, vis_bool_name in VIS_BOOL_MAP.items():
            # Skip groups without visibility bools (kaynnistys, hyvaksyminen, voimaantulo)
            if vis_bool_name is None:
                continue

            # Get the visibility bool value
            vis_bool_value = attr_data.get(vis_bool_name)

            # Only check if vis_bool is explicitly False
            if vis_bool_value is not False:
                continue

            # Get date fields for this group
            date_fields = DEADLINE_GROUP_DATE_FIELDS.get(deadline_group, [])
            
            # Check for stale dates
            stale_fields = []
            for field in date_fields:
                value = attr_data.get(field)
                if value is not None:
                    stale_fields.append({
                        'field': field,
                        'value': value,
                    })

            if stale_fields:
                issues.append((deadline_group, vis_bool_name, stale_fields))

        return issues

    def _print_project_issues(self, project, issues):
        """Print issues found for a single project."""
        subtype_name = project.subtype.name if project.subtype else "?"
        self.stdout.write(self.style.WARNING(
            f"\n⚠️  Project #{project.id} \"{project.name}\" ({subtype_name}):"
        ))
        
        for deadline_group, vis_bool_name, stale_fields in issues:
            self.stdout.write(f"   {vis_bool_name} = false")
            for field_info in stale_fields:
                self.stdout.write(self.style.ERROR(
                    f"      BUT {field_info['field']} = {field_info['value']} (stale!)"
                ))
