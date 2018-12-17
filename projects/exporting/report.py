import copy
import csv
import logging
from collections import OrderedDict

from django.utils.translation import ugettext_lazy as _

from projects.models import Report, Project

logger = logging.getLogger(__name__)

prefix = "report-project-field"


def project_data_headers(report: Report):
    headers = OrderedDict()

    if report.show_name:
        headers[f"{prefix}-name"] = _("name")
    if report.show_created_at:
        headers[f"{prefix}-created_at"] = _("created at")
    if report.show_modified_at:
        headers[f"{prefix}-modified_at"] = _("modified at")
    if report.show_user:
        headers[f"{prefix}-user"] = _("user")
    if report.show_phase:
        headers[f"{prefix}-phase"] = _("phase")
    if report.show_subtype:
        headers[f"{prefix}-subtype"] = _("subtype")

    return headers


def get_project_data_for_report(report: Report, project: Project):
    data = {}

    if report.show_name:
        data[f"{prefix}-name"] = project.name
    if report.show_created_at:
        data[f"{prefix}-created_at"] = project.created_at.isoformat()
    if report.show_modified_at:
        data[f"{prefix}-modified_at"] = project.modified_at.isoformat()
    if report.show_user:
        data[f"{prefix}-user"] = project.user.get_full_name() if project.user else ""
    if report.show_phase:
        data[f"{prefix}-phase"] = project.phase.name if project.phase else ""
    if report.show_subtype:
        data[f"{prefix}-subtype"] = project.subtype.name

    return data


def render_report_to_response(report: Report, projects, response):
    fieldnames = project_data_headers(report)
    attributes = []

    for report_attr in report.report_attributes.all():
        attribute = report_attr.attribute
        attributes.append(attribute)
        fieldnames[attribute.identifier] = attribute.name

    writer = csv.DictWriter(
        response, fieldnames.keys(), restval="", extrasaction="ignore"
    )

    # Write header
    writer.writerow(fieldnames)

    # Write data
    for project in projects:
        data = copy.deepcopy(project.attribute_data)
        data.update(get_project_data_for_report(report, project))

        # Raw values into display values
        for attribute in attributes:
            if attribute.identifier in data:
                try:
                    data[attribute.identifier] = attribute.get_attribute_display(
                        data[attribute.identifier]
                    )
                except Exception:
                    logger.exception(
                        f"Could not handle attribute {attribute} for project {project}."
                    )
        writer.writerow(data)

    return response
