import pytest
from django.http import HttpRequest
from rest_framework.request import Request

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
@pytest.mark.parametrize(
    "request_data, instance, attribute_data",
    [
        ({}, None, {}),
        ([], None, {}),
        (None, None, {}),
        ({"test": "test"}, None, {"test": "test"}),
    ],
)
def test_get_attribute_data(request_data, instance, attribute_data):
    http_request = HttpRequest()
    request = Request(http_request)
    request._full_data = {"attribute_data": request_data}
    assert get_attribute_data(request) == attribute_data


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
