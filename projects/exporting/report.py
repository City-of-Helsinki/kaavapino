import copy
import csv
import logging
from collections import OrderedDict

from django.db.models import Q
from django.utils.translation import gettext_lazy as _
from openpyxl import Workbook

from projects.models import Attribute, Report, Project
from projects.helpers import (
    get_fieldset_path,
    get_flat_attribute_data,
    set_kaavoitus_api_data_in_attribute_data,
    set_ad_data_in_attribute_data,
    set_automatic_attributes,
)

logger = logging.getLogger(__name__)

prefix = "report-project-field"


def project_data_headers(report: Report, limit):
    headers = OrderedDict()

    if report.show_created_at:
        headers[f"{prefix}-created_at"] = _("created at")
    if report.show_modified_at and (not limit or limit > 1):
        headers[f"{prefix}-modified_at"] = _("modified at")

    return headers

def _format_date(value):
    return '{d.day}.{d.month}.{d.year}'.format(d=value)

def _get_display_value(attribute, column, value):
    attr_display = attribute.get_attribute_display(value) or ""

    if column.custom_display_mapping:
        try:
            return column.custom_display_mapping[attr_display]
        except KeyError:
            pass

    return attr_display

def get_project_data_for_report(report: Report, project: Project, limit):
    data = {}

    if report.show_created_at:
        data[f"{prefix}-created_at"] = _format_date(project.created_at)
    if report.show_modified_at and (not limit or limit > 1):
        data[f"{prefix}-modified_at"] = _format_date(project.modified_at)

    return data

def _flatten_fieldset_data(data, path, values={}, index=0):
    if len(path) > 1:
        pass
    else:
        for item in data:
            values[index] = item.get(path[0].identifier)
            index += 1

    return index, values

def _get_fieldset_display(data, path, indent, index, column):
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
                        column,
                    )
                else:
                    attr_display = _get_display_value(attribute, column, value)
                    if j == 0:
                        return_items.append(f"{' '*indent}{i}. {attribute.name}: {attr_display}\n")
                    elif j < len(obj.keys()):
                        return_items.append(f"{' '*(indent+len(str(i))+1)} {attribute.name}: {attr_display}\n")
                    else:
                        return_items.append(f"{' '*(indent+len(str(i))+1)} {attribute.name}: {attr_display}")

    else:
        items = data.get(path[0])
        for i, item in enumerate(items, start=1):
            return_items += _get_fieldset_display(
                item,
                path[1:],
                indent,
                i + (len(items[i-1]) if i > 0 else 0),
                column,
            )

    return "".join(return_items)

def _get_fieldset_children_display(items, attribute, column, offset=1):
    items = [
        f"{i}. {_get_display_value(attribute, column, item)}"
        for i, item in enumerate(items, start=offset)
        if item
    ]
    return "\n".join(items)

def render_report_to_response(
    report: Report, project_ids, response, preview=False, limit=None,
):
    projects = Project.objects.filter(pk__in=project_ids)
    cols = report.columns.order_by("index")
    if preview:
        cols = cols.filter(Q(preview=True) | Q(preview_only=True))
    else:
        cols = cols.filter(preview_only=False)

    if limit:
        extra_cols_sum = sum([report.show_created_at, report.show_modified_at])
        extra_cols_limit = min(extra_cols_sum, limit)
        # adjust limit to accommodate created/modified at columns
        limit = limit - extra_cols_sum
        # limit can't go under 0 or over the sum of all columns
        limit = max(
            limit,
            0,
        )
        limit = min(
            limit,
            cols.count() + extra_cols_sum,
        )
    else:
        limit = None
        extra_cols_limit = None

    fieldnames = project_data_headers(report, extra_cols_limit)

    if limit is not None:
        cols = cols[:limit]

    for col in cols:
        fieldnames[col.id] = \
        col.title or ", ".join([attr.name for attr in col.attributes.all()])

    if preview:
        writer = csv.DictWriter(
            response, fieldnames.keys(), restval="", extrasaction="ignore"
        )
    else:
        workbook = Workbook(write_only=True)
        sheet = workbook.create_sheet()

    # Write header
    if preview:
        writer.writerow(fieldnames)
    else:
        sheet.append([i[1] for i in fieldnames.items()])

    # Write data
    for project in projects:
        data = copy.deepcopy(project.attribute_data)

        try:
            set_kaavoitus_api_data_in_attribute_data(data)
        except Exception:
            pass

        set_ad_data_in_attribute_data(data)
        set_automatic_attributes(data)

        data.update(get_project_data_for_report(
            report, project, extra_cols_limit,
        ))

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
                                fieldset_data, path, 0, 1, col,
                            )
                    elif attr.fieldsets.count():
                        if attr.identifier in flat_data:
                            display_values[attr.identifier] = \
                                _get_fieldset_children_display(
                                    flat_data[attr.identifier], attr, col,
                                )
                    else:
                        if attr.identifier in data:
                            display_values[attr.identifier] = \
                                _get_display_value(
                                    attr,
                                    col,
                                    data[attr.identifier],
                                )

                except AssertionError:
                    logger.exception(
                        f"Could not handle attribute {attr} for project {project}."
                    )

            # combine attribute display values into one string
            data[col.id] = ", ".join([
                str(display_values.get(attr.identifier, ""))
                for attr in col.attributes.all()
                if display_values.get(attr.identifier)
            ])

            # append postfix if any for non-empty fields
            if data[col.id] is None:
                pass
            elif col.postfix_only:
                data[col.id] = col.generate_postfix(project, data)
            else:
                data[col.id] = "".join([
                    data[col.id],
                    col.generate_postfix(project, data),
                ])

        if preview:
            writer.writerow(data)
        else:
            sheet.append([
                i[1] for i in data.items()
                if i[0] in [j[0] for j in fieldnames.items()]
            ])

    if not preview:
        workbook.save(response)

    return response
