import logging
import requests

from django.conf import settings
from django.core.cache import cache

from projects.models import Project
from projects.serializers.project import ProjectDeadlineSerializer

logger = logging.getLogger(__name__)


def refresh_on_map_overview_cache():
    logger.info("Requesting new Geoserver data for all projects")

    for project in Project.objects.all():
        identifier = project.attribute_data.get("hankenumero")

        if not identifier:
            continue

        url = f"{settings.KAAVOITUS_API_BASE_URL}/geoserver/v1/suunnittelualue/{identifier}"

        response = requests.get(
            url,
            headers={"Authorization": f"Token {settings.KAAVOITUS_API_AUTH_TOKEN}"},
        )
        if response.status_code == 200:
            cache.set(url, response, 90000)
        else:
            cache.set(url, response, 180)

def refresh_project_schedule_cache():
    project_schedule_cache = cache.get("serialized_project_schedules", {})
    logger.info(f"Recalculating and caching project schedule for all projects")

    for project in Project.objects.all():
        deadlines = project.deadlines.filter(deadline__subtype=project.subtype)
        schedule = ProjectDeadlineSerializer(
            deadlines,
            many=True,
            allow_null=True,
            required=False,
        ).data
        project_schedule_cache[project.pk] = schedule

    cache.set("serialized_project_schedules", project_schedule_cache, None)
