import copy
import csv
import logging
from collections import OrderedDict

from django.utils.translation import ugettext_lazy as _

from projects.models import Attribute, Report, Project
from projects.helpers import (
    get_fieldset_path,
    get_flat_attribute_data,
    set_kaavoitus_api_data_in_attribute_data,
    set_ad_data_in_attribute_data,
)

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

def _flatten_fieldset_data(data, path, values={}, index=0):
    if len(path) > 1:
        pass
    else:
        for item in data:
            values[index] = item.get(path[0].identifier)
            index += 1

    return index, values

def _get_fieldset_display(data, path, indent, index):
    return_items = []
    if len(path) == 1:
        for i, obj in enumerate(data, start=1):
            for j, (key, value) in enumerate(obj.items()):
                try:
                    attribute = Attribute.objects.get(identifier=key)
                except Attribute.DoesNotExist:
                    continue

                if attribute.value_type == Attribute.TYPE_FIELDSET:
                    if j == 0:
                        return_items.append(f"{' '*indent}{i}. {attribute.name}:\n")
                    else:
                        return_items.append(f"{' '*(indent+len(str(i))+1)} {attribute.name}:\n")
                    return_items += _get_fieldset_display(
                        value,
                        [attribute],
                        indent+4,
                        index+i,
                    )
                else:
                    if j == 0:
                        return_items.append(f"{' '*indent}{i}. {attribute.name}: {attribute.get_attribute_display(value)}\n")
                    elif j < len(obj.keys()):
                        return_items.append(f"{' '*(indent+len(str(i))+1)} {attribute.name}: {attribute.get_attribute_display(value)}\n")
                    else:
                        return_items.append(f"{' '*(indent+len(str(i))+1)} {attribute.name}: {attribute.get_attribute_display(value)}")

    else:
        items = data.get(path[0])
        for i, item in enumerate(items, start=1):
            return_items += _get_fieldset_display(
                item,
                path[1:],
                indent,
                i + (len(items[i-1]) if i > 0 else 0),
            )

    return "".join(return_items)

def _get_fieldset_children_display(items, attribute, offset=1):
    items = [
        f"{i}. {attribute.get_attribute_display(item)}"
        for i, item in enumerate(items, start=offset)
        if item
    ]
    return "\n".join(items)

def render_report_to_response(report: Report, projects, response):
    fieldnames = project_data_headers(report)
    cols = report.columns.order_by("index")

    for col in cols:
        fieldnames[col.id] = \
        col.title or ", ".join([attr.name for attr in col.attributes.all()])

    writer = csv.DictWriter(
        response, fieldnames.keys(), restval="", extrasaction="ignore"
    )

    # Write header
    writer.writerow(fieldnames)

    # Write data
    for project in projects:
        data = copy.deepcopy(project.attribute_data)
        data.update(get_project_data_for_report(report, project))
        try:
            set_kaavoitus_api_data_in_attribute_data(data)
        except Exception:
            pass

        set_ad_data_in_attribute_data(data)
        flat_data = get_flat_attribute_data(data, {})

        # Raw values into display values
        for col in cols:
            # check conditions if any
            if col.condition.count():
                condition_passed = False
                for condition in col.condition.all():
                    if data.get(condition.identifier):
                        condition_passed = True
                        break
            else:
                condition_passed = True

            if not condition_passed:
                data[col.id] = ""
                continue

            # get all related attribute display values
            display_values = {}
            for attr in col.attributes.all():
                try:
                    if attr.value_type == Attribute.TYPE_FIELDSET:
                        path = get_fieldset_path(attr) + [attr]

                        if not path[0].identifier in data:
                            continue

                        fieldset_data = data[path[0].identifier]

                        if attr.fieldsets.count():
                            path = path[1:]

                        display_values[attr.identifier] = \
                            _get_fieldset_display(
                                fieldset_data, path, 0, 1,
                            )
                    elif attr.fieldsets.count():
                        if attr.identifier in flat_data:
                            display_values[attr.identifier] = \
                                _get_fieldset_children_display(
                                    flat_data[attr.identifier], attr,
                                )
                    else:
                        if attr.identifier in data:
                            display_values[attr.identifier] = \
                                attr.get_attribute_display(
                                    data[attr.identifier],
                                )

                except AssertionError:
                    logger.exception(
                        f"Could not handle attribute {attribute} for project {project}."
                    )

            # combine attribute display values into one string
            data[col.id] = ", ".join([
                str(display_values.get(attr.identifier))
                for attr in col.attributes.all()
            ])

            # append postfix if any
            data[col.id] = " ".join([
                data[col.id],
                col.generate_postfix(project, data),
            ])

        writer.writerow(data)

    return response
