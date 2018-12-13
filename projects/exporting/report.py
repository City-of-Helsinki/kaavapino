import copy
import csv
import logging
from collections import OrderedDict

from projects.models import Report

logger = logging.getLogger(__name__)


def render_report_to_response(report: Report, projects, response):
    fieldnames = OrderedDict()
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

        # Raw values into display values
        for attribute in attributes:
            if attribute.identifier in data:
                try:
                    data[attribute.identifier] = attribute.get_attribute_display(
                        data[attribute.identifier]
                    )
                except Exception:
                    logger.exception(
                        f"Couldn't handle attribute {attribute} for project {project}."
                    )
        writer.writerow(data)

    return response
