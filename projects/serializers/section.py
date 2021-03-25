import collections
import copy
import datetime

from django.utils.translation import ugettext_lazy as _
from rest_framework import serializers
from rest_framework.exceptions import ValidationError
from rest_framework_gis.fields import GeometryField

from projects.models import (
    Attribute,
    Project,
    ProjectDeadline,
    ProjectFloorAreaSection,
    ProjectPhaseSection,
    ProjectPhaseDeadlineSection,
    ProjectSubtype,
)
from projects.serializers.utils import _is_attribute_required

from collections import namedtuple

from django.contrib.auth import get_user_model


FIELD_TYPES = {
    Attribute.TYPE_SHORT_STRING: serializers.CharField,
    Attribute.TYPE_LONG_STRING: serializers.CharField,
    Attribute.TYPE_RICH_TEXT: serializers.JSONField,
    Attribute.TYPE_RICH_TEXT_SHORT: serializers.JSONField,
    Attribute.TYPE_LINK: serializers.URLField,
    Attribute.TYPE_INTEGER: serializers.IntegerField,
    Attribute.TYPE_DECIMAL: serializers.DecimalField,
    Attribute.TYPE_BOOLEAN: serializers.NullBooleanField,
    Attribute.TYPE_DATE: serializers.DateField,
    # TODO handle image and file fields later
    Attribute.TYPE_IMAGE: serializers.JSONField,  # TODO: Figure out file uploads with DRF
    Attribute.TYPE_FILE: serializers.JSONField,
    Attribute.TYPE_USER: serializers.PrimaryKeyRelatedField,
    Attribute.TYPE_GEOMETRY: GeometryField,
    Attribute.TYPE_CHOICE: serializers.CharField,
}


FieldData = namedtuple("FieldData", ["field_class", "field_arguments"])


def get_rich_text_validator(attribute):
    def validate(value):
        error_msg = attribute.error_message or _("Character limit exceeded")
        try:
            total_length = 0

            for item in value["ops"]:
                total_length += len(item["insert"])

            if attribute.character_limit and total_length > attribute.character_limit:
                raise ValidationError(
                    {attribute.identifier: error_msg}
                )

            return value

        except (KeyError, TypeError):
            raise ValidationError(
                {attribute.identifier: _("Incorrect rich text formatting")}
            )

    return validate

def get_unique_validator(attribute, project_id):
    def validate(value):
        column = f"attribute_data__{attribute.identifier}"
        error_msg = attribute.error_message or _("Value must be unique")
        if Project.objects.filter(**{column: value}).exclude(pk=project_id).count() > 0:
            raise ValidationError(
                {attribute.identifier: error_msg}
            )

    return validate

def get_deadline_validator(attribute, project_dls, subtype, preview):
    def validate(value):
        if not preview:
            return

        for attr_dl in attribute.deadline.filter(subtype=subtype):
            # validate datetype
            try:
                assert attr_dl.date_type.is_valid_date(value)
            except AttributeError:
                pass
            except AssertionError:
                raise ValidationError(_(
                    f"Invalid date selection for date type {attr_dl.date_type}"
                ))

            # validate minimum distance to previous deadline(s)
            for distance in attr_dl.distances_to_previous.all():
                prev_dl = preview.get(distance.previous_deadline)
                if not prev_dl:
                    continue

                default_error = _(f"Minimum distance to {distance.previous_deadline.abbreviation} not met")

                if type(prev_dl) == str:
                    prev_dl = datetime.datetime.strptime(prev_dl, "%Y-%m-%d").date()

                if distance.date_type and distance.date_type.valid_days_from(
                    prev_dl,
                    distance.distance_from_previous,
                ) > value:
                    raise ValidationError(
                        attr_dl.error_min_distance_previous or default_error
                    )
                elif prev_dl + datetime.timedelta(
                    days=distance.distance_from_previous,
                ) > value:
                    raise ValidationError(
                        attr_dl.error_min_distance_previous or default_error
                    )

    return validate

def create_attribute_field_data(attribute, validation, project, preview):
    """Create data for initializing attribute field serializer."""
    field_arguments = {}
    field_class = FIELD_TYPES.get(attribute.value_type, None)

    field_arguments["validators"] = []

    if attribute.value_type in [Attribute.TYPE_RICH_TEXT, Attribute.TYPE_RICH_TEXT_SHORT]:
        field_arguments["validators"] += [get_rich_text_validator(attribute)]

    if attribute.unique:
        field_arguments["validators"] += [get_unique_validator(attribute, project.pk)]

    if attribute.deadline.count():
        field_arguments["validators"] += [get_deadline_validator(
            attribute,
            project.deadlines,
            project.phase.project_subtype,
            preview,
        )]

    if attribute.value_type == Attribute.TYPE_CHOICE:
        choices = attribute.value_choices.all()
        field_class = serializers.SlugRelatedField
        field_arguments["queryset"] = choices
        field_arguments["slug_field"] = "identifier"

        if attribute.multiple_choice:
            field_arguments["many"] = True

    if attribute.value_type == Attribute.TYPE_USER:
        field_class = serializers.SlugRelatedField
        field_arguments["queryset"] = get_user_model().objects.all()
        field_arguments["slug_field"] = "uuid"

    if attribute.value_type == Attribute.TYPE_DECIMAL:
        field_arguments["max_digits"] = 20
        field_arguments["decimal_places"] = 2

    field_arguments["help_text"] = attribute.help_text

    # Allow fields to be set to null so that they can be emptied
    field_arguments["allow_null"] = True

    field_arguments["required"] = False

    if attribute.value_type == Attribute.TYPE_BOOLEAN:
        field_arguments.pop("allow_null")

    if attribute.multiple_choice and attribute.value_type != Attribute.TYPE_CHOICE:
        if field_class:
            field_arguments["child"] = field_class()
        field_class = serializers.ListField

    return FieldData(field_class, field_arguments)


def create_fieldset_field_data(attribute, validation, project, preview):
    """Dynamically create a serializer for a fieldset type Attribute instance."""
    serializer_fields = {}
    field_arguments = {}

    if attribute.multiple_choice:
        field_arguments["many"] = True

    for attr in attribute.fieldset_attributes.order_by("fieldset_attribute_source"):
        field_data = create_attribute_field_data(attr, validation, project, preview)
        if not field_data.field_class:
            # TODO: Handle this by failing instead of continuing
            continue

        serializer_field = field_data.field_class(**field_data.field_arguments)
        serializer_fields[attr.identifier] = serializer_field

    serializer_fields["_deleted"] = serializers.BooleanField(
        required=False,
        default=False,
    )
    field_arguments["required"] = False

    serializer = type("FieldSetSerializer", (serializers.Serializer,), {})
    serializer._declared_fields = serializer_fields

    return FieldData(serializer, field_arguments)


def create_section_serializer(
    section, context, project=None, validation=True, preview=None,
):
    """
    Dynamically create a serializer for a ProjectPhaseSection or
    ProjectFloorAreaSection instance

    Since a attribute of a section can be dynamically defined, there is
    no way of knowing which fields should be in the serializer before
    checking the current state of the section.

    Additionally, the incoming request is also checked in order to
    get the relevant fields for that exact request. This has to be done
    as the serialization not only relies on the section instance but
    also on the input data field values and their relationship with
    other fields values.
    """

    request = context.get("request", None)
    attribute_data = get_attribute_data(request, project)

    if not request:
        return None

    if isinstance(section, ProjectPhaseSection):
        section_attributes = [
            section_attribute.attribute
            for section_attribute
            in section.projectphasesectionattribute_set.order_by("index")
            if is_relevant_attribute(section_attribute, attribute_data)
        ]
    elif isinstance(section, ProjectFloorAreaSection):
        section_attributes = [
            section_attribute.attribute
            for section_attribute
            in section.projectfloorareasectionattribute_set.order_by("index")
            if is_relevant_attribute(section_attribute, attribute_data)
        ]
    elif isinstance(section, ProjectPhaseDeadlineSection):
        section_attributes = [
            section_attribute.attribute
            for section_attribute
            in section.projectphasedeadlinesectionattribute_set.all()
        ]
    else:
        return None

    serializer_fields = {}
    for attribute in section_attributes:
        if attribute.value_type == Attribute.TYPE_FIELDSET:
            field_data = create_fieldset_field_data(
                attribute, validation, project, preview,
            )
        else:
            field_data = create_attribute_field_data(
                attribute, validation, project, preview,
            )

            if not field_data.field_class:
                # TODO: Handle this by failing instead of continuing
                continue

        serializer_field = field_data.field_class(**field_data.field_arguments)
        serializer_fields[attribute.identifier] = serializer_field

    serializer = type("SectionSerializer", (serializers.Serializer,), {})
    serializer._declared_fields = serializer_fields

    return serializer


def get_attribute_data(request, project=None) -> dict:
    """
    Extract attribute data from request

    Always returns a dict of the attribute data
    no matter the input or value of the attribute data.
    """

    # No need to validate anything if there is no request
    if not request:
        return {}

    # Include any existing project attribute data
    # If we do not copy here then we will override the instance data
    # when doing updates.
    attribute_data = copy.deepcopy(getattr(project, "attribute_data", {}))

    # Extract all attribute data that exists in the request
    request_attribute_data = request.data.get("attribute_data", {})
    if not isinstance(request_attribute_data, collections.Mapping):
        request_attribute_data = {}

    attribute_data.update(request_attribute_data)

    return attribute_data


def is_relevant_attribute(section_attribute, attribute_data) -> bool:
    """
    Check a section attribute is relevant during serialization

    If a field is not relevant, as in the field that it relies
    on is not set to a "truthy" value, then that field can be
    ignored during serialization.
    """
    relies_on_section_attribute = section_attribute.relies_on
    if not relies_on_section_attribute:
        return True

    relies_on_attribute_identifier = relies_on_section_attribute.attribute.identifier
    attribute_data_value = attribute_data.get(relies_on_attribute_identifier)

    return bool(attribute_data_value)
