import pytest

from projects.models import Attribute


@pytest.mark.django_db()
def test_update_attribute_data(f_project, f_project_section_attribute_1):
    attribute_identifier = f_project_section_attribute_1.attribute.identifier

    # Test empty data
    empty_attribute_data = {}
    f_project.update_attribute_data(empty_attribute_data)
    assert f_project.attribute_data == {}

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


@pytest.mark.django_db()
def test_update_fieldset_attribute_data(
    f_fieldset_attribute, project, project_phase_section_attribute_factory
):
    assert f_fieldset_attribute.fieldset_attributes.count() == 2

    # Setup the data
    ppsa = project_phase_section_attribute_factory(attribute=f_fieldset_attribute)

    phase = ppsa.section.phase
    project.phase = phase
    project.save()

    field1 = f_fieldset_attribute.fieldset_attributes.all()[0]
    field2 = f_fieldset_attribute.fieldset_attributes.all()[1]

    data = {
        f_fieldset_attribute.identifier: [
            {field1.identifier: "AAA", field2.identifier: "BBB"}
        ]
    }

    # Verify serialization work
    project.update_attribute_data(data)

    fs_data = project.attribute_data[f_fieldset_attribute.identifier]
    assert len(fs_data) == 1  # List
    assert len(fs_data[0]) == 2

    assert fs_data[0][field1.identifier] == "AAA"
    assert fs_data[0][field2.identifier] == "BBB"


@pytest.mark.django_db()
def test_get_attribute_data_for_fieldset(
    f_fieldset_attribute, project, project_phase_section_attribute_factory
):
    # Setup the data
    ppsa = project_phase_section_attribute_factory(attribute=f_fieldset_attribute)

    phase = ppsa.section.phase

    field1 = f_fieldset_attribute.fieldset_attributes.all()[0]
    field2 = f_fieldset_attribute.fieldset_attributes.all()[1]
    field2.value_type = Attribute.TYPE_INTEGER
    field2.save()

    project.phase = phase
    project.set_attribute_data(
        {
            f_fieldset_attribute.identifier: [
                {field1.identifier: "AAA", field2.identifier: 123}
            ]
        }
    )
    project.save()

    # Verify deserialization work
    fs_data = project.get_attribute_data()[f_fieldset_attribute.identifier]
    assert len(fs_data) == 1  # List
    assert len(fs_data[0]) == 2

    assert fs_data[0][field1.identifier] == "AAA"
    assert fs_data[0][field2.identifier] == 123
