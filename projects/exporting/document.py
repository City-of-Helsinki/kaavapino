import datetime
import io
from html import escape

from django.conf import settings
from django.http import HttpResponse
from django.utils import timezone
from docx.shared import Mm
from docxtpl import DocxTemplate, InlineImage, Listing, RichText

from ..models import Attribute, ProjectPhase, ProjectAttributeFile
from ..models.utils import create_identifier
from projects.helpers import (
    set_kaavoitus_api_data_in_attribute_data,
    set_ad_data_in_attribute_data,
)
from projects.models import ProjectDocumentDownloadLog


IMAGE_WIDTH = Mm(136)

def _get_raw_value(value, attribute):
    if attribute.value_type == Attribute.TYPE_DATE and isinstance(value, str):
        return datetime.datetime.strptime(value, "%Y-%m-%d").date()
    else:
        return value

# TODO: Copied from serializers/utils.py, move under helpers at some point
def _set_fieldset_path(fieldset_content, path, parent_obj, i, identifier, value):
    parent_id = path[i]["parent"].identifier
    index = path[i]["index"]

    try:
        next_obj = parent_obj[parent_id][index]
    except KeyError:
        parent_obj[parent_id] = [None] * (index + 1)
        parent_obj[parent_id][index] = {}
        next_obj = parent_obj[parent_id][index]
    except IndexError:
        parent_obj[parent_id] += [None] * (index + 1 - len(parent_obj[parent_id]))
        next_obj = parent_obj[parent_id][index]


    # TODO multi-level fieldset image uploads not needed/supported for now
    if False and i < len(path) - 1:
        if next_obj is None:
            if fieldset_content:
                parent_obj[parent_id][index] = {**fieldset_content}
            else:
                parent_obj[parent_id][index] = {}

            next_obj = parent_obj[parent_id][index]

        # TODO Handle fieldset_content within multi-level fieldsets later
        _set_fieldset_path(
            None,
            path,
            next_obj,
            i+1,
            identifier,
            value
        )

    else:
        if next_obj is None:
            if fieldset_content:
                parent_obj[parent_id][index] = {
                    **fieldset_content,
                    identifier: value,
                }
            else:
                parent_obj[parent_id][index] = {identifier: value}
        else:
            for k, v in fieldset_content.items():
                next_obj[k] = v

            next_obj[identifier] = value

def render_template(project, document_template, preview):
    doc = DocxTemplate(document_template.file)

    attribute_data_display = {}
    attributes = {a.identifier: a for a in Attribute.objects.all()}

    def get_top_level_attribute(attribute):
        if not attribute.fieldsets.count():
            return attribute
        else:
            return get_top_level_attribute(attribute.fieldsets.first())

    def get_closest_phase(identifier):
        phases = ProjectPhase.objects.filter(
            sections__attributes__identifier=identifier,
            project_subtype=project.subtype,
        ).order_by("index")

        # Returning the closest open phase if found,
        # otherwise return the last phase when the attribute
        # was editable
        phase = phases.filter(index__gte=project.phase.index).first()
        return phase or phases.reverse().first()

    def get_display_and_raw_value(attribute, value):
        empty = False

        if attribute.value_type == Attribute.TYPE_FIELDSET:
            result = []
            for fieldset_item in value or []:
                fieldset_object = {}
                for k, v in fieldset_item.items():
                    item_attr = attributes.get(k)
                    if fieldset_item.get("_deleted") or not item_attr:
                        continue

                    display_value, raw_value = \
                        get_display_and_raw_value(item_attr, v)

                    fieldset_object[k] = display_value

                    if item_attr.value_type != Attribute.TYPE_FIELDSET:
                        fieldset_object[f"{k}__raw"] = raw_value

                result.append(fieldset_object)

            return (result, value)

        if attribute.value_type == Attribute.TYPE_IMAGE and value:
            display_value = InlineImage(doc, value, width=IMAGE_WIDTH)
        else:
            display_value = attribute.get_attribute_display(value)

        if display_value is None or display_value == "":
            empty = True
            if preview:
                display_value = "Tieto puuttuu"

        if attribute.value_type == Attribute.TYPE_LONG_STRING:
            display_value = Listing(display_value)
        if attribute.value_type == Attribute.TYPE_IMAGE:
            pass
        else:
            if preview:
                target_property = None

                if attribute.static_property:
                    target_identifier = None
                    target_property = attribute.static_property

                target_identifier = \
                    get_top_level_attribute(attribute).identifier

                target_phase_id = None
                if target_identifier:
                    try:
                        target_phase_id = get_closest_phase(identifier).id
                    except AttributeError:
                        pass

                # attribute: editable attribute field
                # phase: closest phase where attribute field is located
                # property: editable project model field
                edit_url = settings.DOCUMENT_EDIT_URL_FORMAT.replace(
                    "<pk>", str(project.pk),
                )
                if target_identifier and target_phase_id:
                    edit_url += f"?attribute={target_identifier}&phase={target_phase_id}"
                elif target_property:
                    edit_url += f"?property={target_property}"

                rich_text_args = {
                    "color": "#d0c873" if empty else "#79a6b5",
                    "url_id": doc.build_url_id(edit_url),
                }
            else:
                rich_text_args = {}

            display_value = RichText(display_value, **rich_text_args)

        return (display_value, _get_raw_value(value, attribute))

    attribute_data = project.attribute_data
    try:
        set_kaavoitus_api_data_in_attribute_data(attribute_data)
    except Exception:
        pass

    set_ad_data_in_attribute_data(attribute_data)

    full_attribute_data = [
        (attr, attribute_data.get(attr.identifier))
        for attr in Attribute.objects.all()
    ]

    for attribute, value in full_attribute_data:
        identifier = attribute.identifier
        display_value, raw_value = get_display_and_raw_value(attribute, value)

        attribute_data_display[identifier] = display_value

        if attribute.value_type != Attribute.TYPE_FIELDSET:
            attribute_data_display[identifier + "__raw"] = raw_value

    attribute_files = ProjectAttributeFile.objects \
        .filter(project=project, archived_at=None) \
        .order_by(
            "fieldset_path_str",
            "attribute__pk",
            "project__pk",
            "-created_at",
        ) \
        .distinct("fieldset_path_str", "attribute__pk", "project__pk")

    for attribute_file in attribute_files:
        # only image formats supported by docx can be used
        image_formats = [
            "bmp",
            "emf",
            "emz",
            "eps",
            "fpix", "fpx",
            "gif",
            "jpg", "jpeg", "jfif", "jpeg-2000",
            "pict", "pct",
            "png",
            "pntg",
            "psd",
            "qtif",
            "sgi",
            "tga", "tpic",
            "tiff", "tif",
            "wmf",
            "wmz",
        ]

        file_format_is_supported = \
            attribute_file.file.path.split('.')[-1].lower() in image_formats

        if file_format_is_supported:
            display_value, __ = get_display_and_raw_value(
                attribute_file.attribute,
                attribute_file.file.path,
            )
        elif preview:
            display_value = "Kuvan tiedostotyyppiä ei tueta"
        else:
            continue

        if not attribute_file.fieldset_path:
            attribute_data_display[
                attribute_file.attribute.identifier
            ] = display_value
        else:
            try:
                fieldset_content = attribute_data_display.get(
                    attribute_file.fieldset_path[0]["parent"].identifier, []
                )[attribute_file.fieldset_path[0]["index"]]
            except (KeyError, IndexError, TypeError):
                fieldset_content = {}

            _set_fieldset_path(
                fieldset_content,
                attribute_file.fieldset_path,
                attribute_data_display,
                0,
                attribute_file.attribute.identifier,
                display_value,
            )

    doc.render(attribute_data_display)
    output = io.BytesIO()
    doc.save(output)

    if not preview:
        ProjectDocumentDownloadLog.objects.create(
            project=project,
            document_template=document_template,
            phase=project.phase.common_project_phase,
        )

    return output.getvalue()


def get_document_response(project, document_template, filename=None):
    if filename is None:
        filename = "{}-{}-{}".format(
            create_identifier(project.name),
            document_template.name,
            timezone.now().date(),
        )

    output = render_template(project, document_template)
    response = HttpResponse(
        output,
        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )
    response["Content-Disposition"] = "attachment; filename={}.docx".format(filename)
    response["Access-Control-Allow-Origin"] = "*"
    return response
