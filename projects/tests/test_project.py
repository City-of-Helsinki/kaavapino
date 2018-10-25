import pytest


@pytest.mark.django_db()
def test_update_attribute_data(f_project, f_project_section_attribute_1):
    attribute_identifier = f_project_section_attribute_1.attribute.identifier

    # Test empty data
    empty_attribute_data = {}
    f_project.update_attribute_data(empty_attribute_data)

    # Test add non proper attribute
    attribute_data = {"this_is_no_proper": "test"}
    f_project.update_attribute_data(attribute_data)
    assert f_project.attribute_data == {}

    # Test with proper attribute
    attribute_data = {attribute_identifier: "test"}
    f_project.update_attribute_data(attribute_data)
    assert f_project.attribute_data == {attribute_identifier: "test"}

    # Test None value
    attribute_data = None
    f_project.update_attribute_data(attribute_data)
    assert f_project.attribute_data == {attribute_identifier: "test"}

    # Test add empty value
    attribute_data = {attribute_identifier: None}
    f_project.update_attribute_data(attribute_data)
    assert f_project.attribute_data == {}
