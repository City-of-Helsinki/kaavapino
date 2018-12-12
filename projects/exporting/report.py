import copy
import csv
from collections import OrderedDict

from projects.models import Report


def render_report_to_response(report: Report, projects, response):
    fieldnames = OrderedDict()

    for report_attr in report.report_attributes.all():
        attribute = report_attr.attribute
        fieldnames[attribute.identifier] = attribute.name

    writer = csv.DictWriter(
        response, fieldnames.keys(), restval="", extrasaction="ignore"
    )

    # Write header
    writer.writerow(fieldnames)

    # Write data
    for project in projects:
        data = copy.deepcopy(project.attribute_data)
        writer.writerow(data)

    return response
