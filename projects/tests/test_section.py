import pytest
from django.contrib.auth import get_user_model
from django.http import HttpRequest
from rest_framework import serializers
from rest_framework.request import Request

from projects.models import AttributeValueChoice
from projects.serializers.section import create_attribute_field_data
from projects.serializers.section import (
    create_section_serializer,
    get_attribute_data,
    is_relevant_attribute,
)


@pytest.mark.django_db()
def test_create_section_serializer(
    f_project_section_1, f_project_section_attribute_1, f_project_section_attribute_2
):
    http_request = HttpRequest()
    request = Request(http_request)
    context = {"request": request}
    serializer = create_section_serializer(f_project_section_1, context)
    fields = serializer._declared_fields
    assert len(fields) == 2


@pytest.mark.django_db()
def test_create_section_serialized_for_fieldset(
    f_fieldset_attribute, project, project_phase_section_attribute_factory
):
    # Setup the data
    ppsa = project_phase_section_attribute_factory(attribute=f_fieldset_attribute)
    section = ppsa.section
    phase = section.phase
    project.phase = phase
    project.save()

    field1 = f_fieldset_attribute.fieldset_attributes.all()[0]
    field2 = f_fieldset_attribute.fieldset_attributes.all()[1]

    data = {
        f_fieldset_attribute.identifier: [
            {field1.identifier: "AAA", field2.identifier: "BBB"},
            {field1.identifier: "CCC", field2.identifier: "DDD"},
        ]
    }

    http_request = HttpRequest()
    request = Request(http_request)
    context = {"request": request}
    serializer = create_section_serializer(section, context)
    fields = serializer._declared_fields
    assert len(fields) == 1

    assert serializer(data=data).is_valid()




@pytest.mark.django_db()
@pytest.mark.parametrize(
    "request_data, project, attribute_data",
    [
        ({}, None, {}),
        ([], None, {}),
        (None, None, {}),
        ({"test": "test"}, None, {"test": "test"}),
        (
            {},
            pytest.lazy_fixture("f_project_with_attribute_data"),
            {"test": "test", "test2": "test2"},
        ),
        (
            {"hello": "test"},
            pytest.lazy_fixture("f_project_with_attribute_data"),
            {"test": "test", "test2": "test2", "hello": "test"},
        ),
    ],
)
def test_get_attribute_data(request_data, project, attribute_data):
    http_request = HttpRequest()
    request = Request(http_request)
    request._full_data = {"attribute_data": request_data}
    assert get_attribute_data(request, project) == {
        **attribute_data,
        **(
            {
                "kaavaprosessin_kokoluokka": project.subtype.name,
                "kaavaprosessin_kokoluokka_readonly": project.subtype.name,
                "kaavan_vaihe": project.phase.prefixed_name,
            }
            if project else {}
        ),
    }


@pytest.mark.django_db()
def test_is_relevant_attribute(
    f_project_section_attribute_5, f_project_section_attribute_6
):
    assert is_relevant_attribute(f_project_section_attribute_5, {}) is True
    assert is_relevant_attribute(f_project_section_attribute_6, {}) is False
    assert (
        is_relevant_attribute(
            f_project_section_attribute_6,
            {f_project_section_attribute_5.attribute.identifier: True},
        )
        is True
    )


@pytest.mark.django_db()
def test_create_attribute_field_data(
    f_short_string_attribute,
    f_user_attribute,
    f_multi_choice_attribute,
    f_choice_attribute,
    project,
):
    short_string_field = create_attribute_field_data(
        f_short_string_attribute,
        True,
        project,
        None,
    )
    user_field = create_attribute_field_data(
        f_user_attribute,
        True,
        project,
        None,
    )
    multi_choice_field = create_attribute_field_data(
        f_multi_choice_attribute,
        True,
        project,
        None,
    )
    choice_field = create_attribute_field_data(
        f_choice_attribute,
        True,
        project,
        None,
    )

    fields = [short_string_field, user_field, multi_choice_field, choice_field]
    choices_field = [multi_choice_field, choice_field]

    assert short_string_field.field_class == serializers.CharField
    assert user_field.field_class == serializers.SlugRelatedField
    assert multi_choice_field.field_class == serializers.SlugRelatedField
    assert choice_field.field_class == serializers.SlugRelatedField

    for field in fields:
        assert "help_text" in field.field_arguments

    for choice_field in choices_field:
        assert len(choice_field.field_arguments["queryset"]) > 0
        assert (
            type(choice_field.field_arguments["queryset"].first())
            == AttributeValueChoice
        )

    assert len(user_field.field_arguments["queryset"]) == len(
        get_user_model().objects.all()
    )
    assert type(user_field.field_arguments["queryset"].first()) == get_user_model()
