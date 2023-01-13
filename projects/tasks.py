import copy
import logging
import re

import requests
from typing import Optional, Any

from django.conf import settings
from django.core.cache import cache
from django.http import HttpResponse

from projects.exporting.report import render_report_to_response
from projects.models import Project, ProjectDeadline, Report
from projects.serializers.project import ProjectDeadlineSerializer
from projects.helpers import set_kaavoitus_api_data_in_attribute_data

logger = logging.getLogger(__name__)


def refresh_on_map_overview_cache() -> None:
    logger.info("Requesting new Geoserver data for all projects")

    project: Project
    for project in Project.objects.all():
        identifier: str = project.attribute_data.get("hankenumero")

        if not identifier or not re.compile("^\d{4}_\d{1,3}$").match(identifier):
            continue

        url = f"{settings.KAAVOITUS_API_BASE_URL}/geoserver/v1/suunnittelualue/{identifier}"

        response = requests.get(
            url,
            headers={"Authorization": f"Token {settings.KAAVOITUS_API_AUTH_TOKEN}"},
        )
        if response.status_code == 200:
            cache.set(url, response, 86400)  # 1 day
        elif response.status_code == 404:
            cache.set(url, response, 28800)  # 8 hours
        else:
            cache.set(url, response, 3600)  # 1 hour


def refresh_project_schedule_cache() -> None:
    project_schedule_cache: dict[str, dict[str, str]] = cache.get("serialized_project_schedules", {})
    logger.info(f"Recalculating and caching project schedule for all projects")

    project: Project
    for project in Project.objects.all():
        deadlines: list[ProjectDeadline] = project.deadlines.filter(deadline__subtype=project.subtype)
        schedule = ProjectDeadlineSerializer(
            deadlines,
            many=True,
            allow_null=True,
            required=False,
        ).data
        project_schedule_cache[project.pk] = schedule

    cache.set("serialized_project_schedules", project_schedule_cache, None)


# generate all reports to make sure as much freshly cached data as possible
# is available when users request reports
def cache_report_data(project_ids: list[Any] = None) -> None:
    if not project_ids:
        project_ids = [
            project.pk for project in Project.objects.filter(
                onhold=False, public=True,
            )
        ]
    report: Report
    for report in Report.objects.all():
        if report.previewable:
            render_report_to_response(
                report, project_ids, HttpResponse(), True,
            )

        render_report_to_response(
            report, project_ids, HttpResponse(), False,
        )

def cache_queued_project_report_data() -> None:
    cache_key = 'projects.tasks.cache_selected_report_data.queue'
    queue: list[Any] = cache.get(cache_key)
    cache.set(cache_key, [], None)

    if queue:
        cache_report_data(queue)


def cache_kaavoitus_api_data():
    projects = Project.objects.all()
    logger.info(f"Caching Kaavoitus-API data for {len(projects)} projects")

    for project in projects:
        try:
            data = copy.deepcopy(project.attribute_data)
            set_kaavoitus_api_data_in_attribute_data(data, use_cached=False)
        except Exception as e:
            logger.error(e)

    logger.info(f"Finished caching Kaavoitus-API data for {len(projects)} projects")
