from rest_framework import serializers

from projects.serializers.utils import (
    _get_serializer_field_data,
    _is_attribute_required,
)


def create_section_serializer(section):
    serializer_fields = {}
    for section_attribute in section.projectphasesectionattribute_set.order_by("index"):
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
