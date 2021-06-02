import logging

from django.core.management.base import BaseCommand, CommandError
from django.core.cache import cache

from projects.models import Project
from projects.serializers.project import ProjectDeadlineSerializer

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Update caches for project schedules"

    def handle(self, *args, **options):
        project_schedule_cache = cache.get("serialized_project_schedules", {})

        for project in Project.objects.all():
            deadlines = project.deadlines.filter(deadline__subtype=project.subtype)
            schedule = ProjectDeadlineSerializer(
                deadlines,
                many=True,
                allow_null=True,
                required=False,
            ).data
            project_schedule_cache[project.pk] = schedule
            logger.info(f"{project} schedule cached")

        logger.info("Saving cache")
        cache.set("serialized_project_schedules", project_schedule_cache, None)
