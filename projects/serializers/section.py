import collections

from rest_framework import serializers

from projects.serializers.utils import (
    _get_serializer_field_data,
    _is_attribute_required,
)


def create_section_serializer(section, context):
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
    attribute_data = get_attribute_data(request)

    if not request:
        return None

    serializer_fields = {}
    for section_attribute in section.projectphasesectionattribute_set.order_by("index"):
        if not is_relevant_attribute(section_attribute, attribute_data):
            continue
        attribute = section_attribute.attribute
        field_data = _get_serializer_field_data(attribute)

        if not field_data.field_class:
            # TODO: Handle this by failing instead of continuing
            continue

        field_data.field_arguments["required"] = _is_attribute_required(
            section_attribute
        )

        serializer_field = field_data.field_class(**field_data.field_arguments)
        serializer_fields[attribute.identifier] = serializer_field

    serializer = serializers.Serializer
    serializer._declared_fields = serializer_fields

    return serializer


def get_attribute_data(request) -> dict:
    """
    Extract attribute data from request

    Always returns a dict of the attribute data
    no matter the input or value of the attribute data.
    """
    if not request:
        return {}

    attribute_data = request.data.get("attribute_data", {})
    if not isinstance(attribute_data, collections.Mapping):
        attribute_data = {}

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
