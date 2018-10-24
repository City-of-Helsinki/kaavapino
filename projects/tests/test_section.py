import pytest

from projects.serializers.section import create_section_serializer


@pytest.mark.django_db()
def test_create_section_serializer(
    f_project_section_1, f_project_section_attribute_1, f_project_section_attribute_2
):
    serializer = create_section_serializer(f_project_section_1)
    fields = serializer._declared_fields
    assert len(fields) == 2
