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
from projects.deadline_utils import find_stale_deadline_fields

logger = logging.getLogger(__name__)


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
        # Find stale fields using shared utility
        stale_data = find_stale_deadline_fields(project.attribute_data)
        
        # Convert to the format needed for cleanup
        cleaned_fields = []
        for deadline_group, vis_bool_name, stale_fields in stale_data:
            for field_info in stale_fields:
                cleaned_fields.append({
                    'group': deadline_group,
                    'vis_bool': vis_bool_name,
                    'field': field_info['field'],
                    'old_value': field_info['value'],
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
