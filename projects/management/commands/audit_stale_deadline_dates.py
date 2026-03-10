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
from projects.deadline_utils import find_stale_deadline_fields

logger = logging.getLogger(__name__)


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
        
        Returns a list of tuples: [(deadline_group, vis_bool_name, stale_fields), ...]
        """
        return find_stale_deadline_fields(project.attribute_data)

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
