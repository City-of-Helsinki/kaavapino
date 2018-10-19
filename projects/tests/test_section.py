import pytest
from django.contrib.auth import get_user_model
from rest_framework import serializers

from projects.models import Attribute, AttributeValueChoice
from projects.serializers.section import (
    create_section_serializer,
    _is_attribute_required,
    _get_serializer_field_data,
)


@pytest.mark.django_db()
def test_create_section_serializer(
    f_project_section_1, f_project_section_attribute_1, f_project_section_attribute_2
):
    serializer = create_section_serializer(f_project_section_1)
    fields = serializer._declared_fields
    assert len(fields) == 2


@pytest.mark.django_db()
def test_is_attribute_required(f_project_section_attribute_1):
    required = _is_attribute_required(f_project_section_attribute_1)
    assert required is False

    # required = True
    f_project_section_attribute_1.required = True
    required = _is_attribute_required(f_project_section_attribute_1)
    assert required is True

    # required = True, generated = True
    f_project_section_attribute_1.generated = True
    required = _is_attribute_required(f_project_section_attribute_1)
    assert required is False

    # required = True, generated = False, Boolean field
    f_project_section_attribute_1.generated = False
    f_project_section_attribute_1.attribute.value_type = Attribute.TYPE_BOOLEAN
    required = _is_attribute_required(f_project_section_attribute_1)
    assert required is False


@pytest.mark.django_db()
def test_get_serializer_field_data(
    f_short_string_attribute,
    f_user_attribute,
    f_short_string_multi_choice_attribute,
    f_short_string_choice_attribute,
):
    short_string_field = _get_serializer_field_data(f_short_string_attribute)
    user_field = _get_serializer_field_data(f_user_attribute)
    multi_choice_field = _get_serializer_field_data(
        f_short_string_multi_choice_attribute
    )
    choice_field = _get_serializer_field_data(f_short_string_choice_attribute)

    fields = [short_string_field, user_field, multi_choice_field, choice_field]
    choices_field = [multi_choice_field, choice_field]

    assert short_string_field.field_class == serializers.CharField
    assert user_field.field_class == serializers.PrimaryKeyRelatedField
    assert multi_choice_field.field_class == serializers.MultipleChoiceField
    assert choice_field.field_class == serializers.CharField

    for field in fields:
        assert "help_text" in field.field_arguments

    for choice_field in choices_field:
        assert len(choice_field.field_arguments["choices"]) > 0
        assert (
            type(choice_field.field_arguments["choices"].first())
            == AttributeValueChoice
        )

    assert len(user_field.field_arguments["queryset"]) == len(
        get_user_model().objects.all()
    )
    assert type(user_field.field_arguments["queryset"].first()) == get_user_model()
