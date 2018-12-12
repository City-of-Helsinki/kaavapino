import collections
import copy

from rest_framework import serializers

from projects.models import Attribute
from projects.serializers.utils import _is_attribute_required

from collections import namedtuple

from django.contrib.auth import get_user_model


FIELD_TYPES = {
    Attribute.TYPE_SHORT_STRING: serializers.CharField,
    Attribute.TYPE_LONG_STRING: serializers.CharField,
    Attribute.TYPE_INTEGER: serializers.IntegerField,
    Attribute.TYPE_BOOLEAN: serializers.BooleanField,
    Attribute.TYPE_DATE: serializers.DateField,
    Attribute.TYPE_IMAGE: serializers.ImageField,  # TODO: Figure out file uploads with DRF
    Attribute.TYPE_FILE: serializers.FileField,
    Attribute.TYPE_USER: serializers.PrimaryKeyRelatedField,
    # TODO Add Attribute.TYPE_GEOMETRY
}


FieldData = namedtuple("FieldData", ["field_class", "field_arguments"])


def create_attribute_field_data(attribute, validation):
    """Create data for initializing attribute field serializer."""
    field_arguments = {}
    field_class = FIELD_TYPES.get(attribute.value_type, None)

    choices = attribute.value_choices.all()
    if choices:
        field_class = serializers.SlugRelatedField
        field_arguments["queryset"] = choices
        field_arguments["slug_field"] = "identifier"

        if attribute.multiple_choice:
            field_arguments["many"] = True

    if attribute.value_type == Attribute.TYPE_USER:
        field_class = serializers.SlugRelatedField
        field_arguments["queryset"] = get_user_model().objects.all()
        field_arguments["slug_field"] = "uuid"

    field_arguments["help_text"] = attribute.help_text

    # Allow fields to be set to null so that they can be emptied
    field_arguments["allow_null"] = True

    field_arguments["required"] = False
    if validation:
        field_arguments["required"] = _is_attribute_required(attribute)
        field_arguments["allow_null"] = False

    if attribute.value_type == Attribute.TYPE_BOOLEAN:
        field_arguments.pop("allow_null")

    return FieldData(field_class, field_arguments)


def create_fieldset_field_data(attribute, validation):
    """Dynamically create a serializer for a fieldset type Attribute instance."""
    serializer_fields = {}
    field_arguments = {}

    if attribute.multiple_choice:
        field_arguments["many"] = True

    for attr in attribute.fieldset_attributes.order_by("fieldset_attribute_source"):
        field_data = create_attribute_field_data(attr, validation)
        if not field_data.field_class:
            # TODO: Handle this by failing instead of continuing
            continue

        serializer_field = field_data.field_class(**field_data.field_arguments)
        serializer_fields[attr.identifier] = serializer_field

    field_arguments["required"] = False
    if validation:
        field_arguments["required"] = _is_attribute_required(attribute)
        field_arguments["allow_null"] = False

    serializer = type("FieldSetSerializer", (serializers.Serializer,), {})
    serializer._declared_fields = serializer_fields

    return FieldData(serializer, field_arguments)


def create_section_serializer(section, context, project=None, validation=True):
    """
    Dynamically create a serializer for a ProjectPhaseSection instance

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

    serializer_fields = {}
    for section_attribute in section.projectphasesectionattribute_set.order_by("index"):
        if not is_relevant_attribute(section_attribute, attribute_data):
            continue
        attribute = section_attribute.attribute

        if attribute.value_type == Attribute.TYPE_FIELDSET:
            field_data = create_fieldset_field_data(attribute, validation)
        else:
            field_data = create_attribute_field_data(attribute, validation)

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
