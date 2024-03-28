import logging

from django.core.management.base import BaseCommand
from django_q.models import Schedule

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Create schedules for scheduled tasks"
    def add_arguments(self, parser):
        parser.add_argument(
            "--overwrite", nargs="?", type=bool,
            help="Overwrite existing schedules with defaults"
        )

    def handle(self, *args, **options):
        schedules = [
            {
                "func": "projects.tasks.refresh_on_map_overview_cache",
                "defaults": {
                    "schedule_type": Schedule.CRON,
                    "cron": "0 0 * * *",
                }
            },
            {
                "func": "projects.tasks.cache_report_data",
                "defaults": {
                    "schedule_type": Schedule.CRON,
                    "cron": "0 */8 * * *",
                }
            },
            {
                "func": "projects.tasks.cache_queued_project_report_data",
                "defaults": {
                    "schedule_type": Schedule.MINUTES,
                    "minutes": 20,
                }
            },
            {
                "func": "projects.tasks.cache_kaavoitus_api_data",
                "defaults": {
                    "schedule_type": Schedule.CRON,
                    "cron": "0 4 * * *",
                }
            },
            {
                "func": "projects.tasks.check_archived_projects",
                "defaults": {
                    "schedule_type": Schedule.CRON,
                    "cron": "0 2 * * *"
                }
            }
        ]
        for schedule in schedules:
            if options.get("overwrite"):
                _, created = Schedule.objects.update_or_create(
                    func=schedule.get("func"),
                    defaults=schedule.get("defaults"),
                )
                updated = not created
            else:
                _, created = Schedule.objects.get_or_create(
                    func=schedule.get("func"),
                    defaults=schedule.get("defaults"),
                )
                updated = False

            if created:
                logger.info(f"Created new schedule for {schedule.get('func')}")
            elif updated:
                logger.info(f"Created new schedule for {schedule.get('func')}")
            else:
                logger.info(f"Already scheduled, ignoring {schedule.get('func')}")
