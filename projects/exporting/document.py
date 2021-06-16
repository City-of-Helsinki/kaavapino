import io
from html import escape

from django.conf import settings
from django.http import HttpResponse
from django.utils import timezone
from docx.shared import Mm
from docxtpl import DocxTemplate, InlineImage, Listing, RichText

from ..models import Attribute, ProjectPhase
from ..models.utils import create_identifier
from projects.helpers import (
    set_kaavoitus_api_data_in_attribute_data,
    set_ad_data_in_attribute_data,
)

IMAGE_WIDTH = Mm(136)


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

    def get_display_value(attribute, value):
        empty = False

        if attribute.value_type == Attribute.TYPE_FIELDSET:
            return [
                {
                    k: get_display_value(attributes.get(k), v)
                    for k, v in fieldset_item.items()
                    if attributes.get(k)
                }
                for fieldset_item in value or []
                if not fieldset_item.get("_deleted")
            ]

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

        return display_value

    attribute_data = project.attribute_data
    try:
        set_kaavoitus_api_data_in_attribute_data(attribute_data)
    except Exception:
        pass

    set_ad_data_in_attribute_data(attribute_data)

    for identifier, value in attribute_data.items():
        attribute = attributes.get(identifier)
        if not attribute:
            continue

        display_value = get_display_value(attribute, value)

        attribute_data_display[identifier] = display_value

    doc.render(attribute_data_display)
    output = io.BytesIO()
    doc.save(output)
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
