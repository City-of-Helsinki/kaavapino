import copy
import logging
import re

import requests
from requests.exceptions import Timeout
import datetime

from django.conf import settings
from django.core.cache import cache
from django.http import HttpResponse
from django.utils import timezone

from projects.exporting.report import render_report_to_response
from projects.models import Project, Report, DataRetentionPlan
from projects.serializers.project import ProjectDeadlineSerializer
from projects.helpers import set_kaavoitus_api_data_in_attribute_data

logger = logging.getLogger(__name__)

VALID_IDENTIFIER_PATTERN = re.compile("^\d{4}_\d{1,3}$")


def get_active_projects_queryset():
    return Project.objects.filter(
        archived=False,
        onhold=False,
        modified_at__gte=timezone.now()-datetime.timedelta(days=7)
    )


def refresh_on_map_overview_cache():
    projects = get_active_projects_queryset()
    logger.info(f"Caching Geoserver data for {len(projects)} projects")
    for project in projects:
        identifier = project.attribute_data.get("hankenumero")
        if not identifier or not VALID_IDENTIFIER_PATTERN.match(identifier):
            logger.info(f"Project {project.name} has invalid hankenumero: {identifier}")
            continue

        url = f"{settings.KAAVOITUS_API_BASE_URL}/geoserver/v1/suunnittelualue/{identifier}"
        try:
            response = requests.get(
                url,
                headers={"Authorization": f"Token {settings.KAAVOITUS_API_AUTH_TOKEN}"},
                timeout=10,
            )
            if response.status_code == 200:
                cache.set(url, response.json(), 86400)
            else:
                logger.info(f"Invalid request response {response.status_code} for {identifier}")
        except Timeout:
            logger.warning(f"Timeout while caching Geoserver data for hankenumero {identifier}")
            pass
        except Exception as exc:
            logger.warning(f"Exception while caching Geoserver data for hankenumero {identifier}", exc)

def refresh_project_schedule_cache():
    project_schedule_cache = cache.get("serialized_project_schedules", {})
    logger.info(f"Recalculating and caching project schedule for all active projects")

    for project in get_active_projects_queryset():
        deadlines = project.deadlines.filter(deadline__subtype=project.subtype)
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
def cache_report_data(project_ids=None):
    if not project_ids:
        project_ids = [
            project.pk for project in Project.objects.filter(
                onhold=False, public=True,
            )
        ]
    for report in Report.objects.all():
        if report.previewable:
            render_report_to_response(
                report, project_ids, HttpResponse(), True,
            )

        render_report_to_response(
            report, project_ids, HttpResponse(), False,
        )


def cache_queued_project_report_data():
    cache_key = 'projects.tasks.cache_selected_report_data.queue'
    queue = cache.get(cache_key)
    cache.set(cache_key, [], None)

    if queue:
        cache_report_data(queue)


def cache_kaavoitus_api_data():
    projects = get_active_projects_queryset()
    logger.info(f"Caching Kaavoitus-API data for {len(projects)} projects")

    for project in projects:
        try:
            data = copy.deepcopy(project.attribute_data)
            set_kaavoitus_api_data_in_attribute_data(data, use_cached=False)
        except Exception as e:
            logger.error(e)

    logger.info(f"Finished caching Kaavoitus-API data for {len(projects)} projects")


def check_archived_projects():
    archived_projects = Project.objects.filter(archived=True, archived_at__isnull=False)
    logger.info(f"Checking {len(archived_projects)} archived projects")

    custom_data_retention_plans = DataRetentionPlan.objects.filter(plan_type=DataRetentionPlan.TYPE_CUSTOM)
    for project in archived_projects:
        diff_days = (timezone.now() - project.archived_at).days
        for data_retention_plan in custom_data_retention_plans:
            diff = diff_days if data_retention_plan.custom_time_unit == DataRetentionPlan.UNIT_DAYS \
                else diff_days / 30 if data_retention_plan.custom_time_unit == DataRetentionPlan.UNIT_MONTHS \
                else diff_days / 365 if data_retention_plan.custom_time_unit == DataRetentionPlan.UNIT_YEARS \
                else None

            if diff is None:
                logger.warning(f"Diff should not be none, data_retention_plan.custom_time_unit '{data_retention_plan.custom_time_unit}' might be invalid")
                continue

            if diff > data_retention_plan.custom_time:
                project.clear_data_by_data_retention_plan(data_retention_plan)

        if (diff_days / 365) > 5:  # Clear audit log data after 5 years has passed from archived_at
            project.clear_audit_log_data()

