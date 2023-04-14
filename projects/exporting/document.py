import datetime
import io
from html import escape
import logging
import jinja2
from jinja2 import Environment, exceptions, meta

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.dml import MSO_THEME_COLOR
from pptx.enum.shapes import MSO_SHAPE_TYPE
from pptx.parts.image import Image

from django.conf import settings
from django.http import HttpResponse
from django.utils import timezone
from docx.shared import Mm
from docxtpl import DocxTemplate, InlineImage, Listing, RichText

from ..models import Attribute, ProjectPhase, ProjectAttributeFile
from ..models.utils import create_identifier
from projects.helpers import (
    DOCUMENT_CONTENT_TYPES,
    get_file_type,
    set_kaavoitus_api_data_in_attribute_data,
    set_ad_data_in_attribute_data,
    set_automatic_attributes,
)
from projects.models import ProjectDocumentDownloadLog

log = logging.getLogger(__name__)


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


def get_top_level_attribute(attribute):
    if not attribute.fieldsets.count():
        return attribute
    else:
        return get_top_level_attribute(attribute.fieldsets.first())


def get_closest_phase(project, identifier):
    phases = ProjectPhase.objects.filter(
        sections__attributes__identifier=identifier,
        project_subtype=project.subtype,
    ).order_by("index")

    # Returning the closest open phase if found,
    # otherwise return the last phase when the attribute
    # was editable
    phase = phases.filter(index__gte=project.phase.index).first()
    return phase or phases.reverse().first()


def render_template(project, document_template, preview):
    doc_type = get_file_type(document_template.file.path)

    if doc_type == 'docx':
        doc = DocxTemplate(document_template.file)
    else:
        doc = None

    attribute_data_display = {}
    attribute_element_data = {}
    attributes = {a.identifier: a for a in Attribute.objects.all()}

    def get_display_and_raw_value(attribute, value, ignore_multiple_choice=False):
        empty = False
        text_args = None
        element_data = {}

        if attribute.value_type == Attribute.TYPE_FIELDSET:
            result = []
            for fieldset_item in value or []:
                fieldset_object = {}
                for k, v in fieldset_item.items():
                    item_attr = attributes.get(k)
                    if fieldset_item.get("_deleted") or not item_attr:
                        continue

                    display_value, raw_value, element_data = \
                        get_display_and_raw_value(item_attr, v)

                    fieldset_object[k] = display_value

                    if item_attr.value_type != Attribute.TYPE_FIELDSET:
                        fieldset_object[f"{k}__raw"] = raw_value

                if fieldset_object:
                    result.append(fieldset_object)

            return (result, value, element_data)
        elif attribute.multiple_choice and not ignore_multiple_choice:
            value = value or []
            display_list = [
                get_display_and_raw_value(
                    attribute, i, ignore_multiple_choice=True
                )[0] for i in value
            ]
            raw_list = [
                _get_raw_value(i, attribute) for i in value
            ]
            all_element_data = [
                get_display_and_raw_value(
                    attribute, i, ignore_multiple_choice=True
                )[2] for i in value
            ]
            if all_element_data:
                element_data = all_element_data[0]

            return (display_list, raw_list, element_data)

        if attribute.value_type == Attribute.TYPE_IMAGE and value:
            if doc_type == 'docx':
                display_value = InlineImage(doc, value)
            else:
                display_value = value
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
                        target_phase_id = get_closest_phase(project, identifier).id
                    except AttributeError:
                        pass

                # attribute: editable attribute field
                # phase: closest phase where attribute field is located
                # property: editable project model field
                # view: default | deadlines | floorarea
                edit_url = settings.DOCUMENT_EDIT_URL_FORMAT.replace(
                    "<pk>", str(project.pk),
                )

                if attribute.projectphasedeadlinesectionattribute_set.count():
                    view = "deadlines"
                elif attribute.projectfloorareasectionattribute_set.count():
                    view = "floorarea"
                else:
                    view = "default"

                if target_identifier and target_phase_id:
                    edit_url += f"?attribute={target_identifier}&phase={target_phase_id}&view={view}"
                elif target_identifier:
                    edit_url += f"?attribute={target_identifier}&view={view}"
                elif target_property:
                    edit_url += f"?property={target_property}&view={view}"

                text_args = {
                    "color": "#d0c873" if empty else "#79a6b5",
                    "url_id": doc.build_url_id(edit_url) if doc_type == 'docx' else edit_url,
                }
            else:
                text_args = {}

            if doc_type == 'docx':
                display_value = RichText(display_value, **text_args)

        return (display_value, _get_raw_value(value, attribute), text_args)

    attribute_data = project.attribute_data
    try:
        set_kaavoitus_api_data_in_attribute_data(attribute_data)
    except Exception:
        pass

    set_ad_data_in_attribute_data(attribute_data)
    set_automatic_attributes(attribute_data)

    full_attribute_data = [
        (attr, attribute_data.get(attr.identifier))
        for attr in Attribute.objects.all()
    ]

    for attribute, value in full_attribute_data:
        identifier = attribute.identifier
        display_value, raw_value, element_data = get_display_and_raw_value(
            attribute,
            value
        )

        attribute_data_display[identifier] = display_value
        attribute_element_data[identifier] = element_data

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
        # only image formats supported by docx/pptx can be used
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
            display_value, __, __ = get_display_and_raw_value(
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

    jinja_env = jinja2.Environment()
    jinja_env.filters['distinct'] = distinct

    if doc_type == 'docx':
        doc.render(attribute_data_display, jinja_env)
        output = io.BytesIO()
        doc.save(output)
    else:
        data = {
            'data': attribute_data_display,
            'element_data': attribute_element_data,
        }
        doc = PptxTemplate(document_template.file, data, env=jinja_env)
        output = doc.save()

    if not preview:
        ProjectDocumentDownloadLog.objects.create(
            project=project,
            document_template=document_template,
            phase=project.phase.common_project_phase,
        )

    return output.getvalue()


# Custom filter for filtering objects from list by unique key
def distinct(value, key):
    if value and type(value) is list:
        checked = set()
        filtered = [e for e in value
            if e.get(key) and e.get(key) not in checked
            and not checked.add(e.get(key))
        ]

        return filtered

    return value


def get_document_response(project, document_template, filename=None):
    if filename is None:
        filename = "{}-{}-{}".format(
            create_identifier(project.name),
            document_template.name,
            timezone.now().date(),
        )

    doc_type = get_file_type(document_template.file.path)
    output = render_template(project, document_template)
    response = HttpResponse(
        output,
        content_type=DOCUMENT_CONTENT_TYPES[doc_type]
    )
    response["Content-Disposition"] = "attachment; filename={}.{}".format(filename, doc_type)
    response["Access-Control-Allow-Origin"] = "*"
    return response


class PptxTemplate:
    def __init__(self, template_file, data, env):
        self.template_file = template_file
        self.data = data['data']
        self.element_data = data['element_data']
        self.env = env

    def save(self):
        doc = Presentation(self.template_file)
        for slide in doc.slides:
            self.render_slide(slide)

        output = io.BytesIO()
        doc.save(output)
        return output

    def render_slide(self, slide):
        for shape in slide.shapes:
            self.render_shape(shape)

    def render_shape(self, shape):
        if shape.has_text_frame:
            self.render_text_frame(shape.text_frame)
        if shape.shape_type == MSO_SHAPE_TYPE.PICTURE:
            self.render_picture(shape)

    def render_picture(self, shape):
        img = self.data.get(shape.name)
        if img:
            parent = shape._parent
            try:
                new_picture = parent.add_picture(
                    img,
                    shape.left,
                    shape.top,
                    height=shape.height
                )
            except FileNotFoundError:
                pass
            parent.element.remove(shape._element)

    def render_text_frame(self, text_frame):
        for paragraph in text_frame.paragraphs:
            self.render_paragraph(paragraph)

    def render_paragraph(self, paragraph):
        original_text = paragraph.text
        env = self.env.from_string(original_text)
        rendered = env.render(self.data)

        # "Clear" all but one run and use it to retain template's text styles
        p = paragraph._p
        for idx, run in enumerate(paragraph.runs):
            if idx == 0 and rendered.strip():
                continue
            p.remove(run._r)

        if paragraph.runs:
            template = self.env.parse(original_text)
            vars = self.get_cleaned_context_variables(template)
            rendered = self.clean_empty_lines(rendered)
            paragraph.runs[0].text = rendered

            if len(vars) == 1:
                link_data = self.element_data.get(vars.pop())
                if link_data:
                    font = paragraph.runs[0].font
                    paragraph.runs[0].hyperlink.address = link_data['url_id']

        # Clean up potential empty paragraph
        if not paragraph.text.strip():
            p = paragraph._p
            p.getparent().remove(p)

    def clean_empty_lines(self, rendered_text):
        return '\n'.join([txt for txt in rendered_text.split('\n') if txt.strip()])

    def get_cleaned_context_variables(self, template):
        return set([
            v for v in meta.find_undeclared_variables(template)
            if '__raw' not in v and 'sorted' != v
        ])
