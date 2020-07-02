import pytest
from django.contrib.auth import get_user_model

from projects.models import (
    Attribute,
    ProjectType,
    ProjectSubtype,
    ProjectPhase,
    ProjectPhaseSection,
    ProjectPhaseSectionAttribute,
    AttributeValueChoice,
    Project,
)


@pytest.fixture()
@pytest.mark.django_db()
def f_user():
    return get_user_model().objects.create(
        username="test", email="test@example.com", first_name="Tim", last_name="Tester"
    )


@pytest.fixture()
@pytest.mark.django_db()
def f_admin(f_user):
    f_user.is_superuser = True
    f_user.is_staff = True
    f_user.save()
    return f_user


@pytest.fixture()
@pytest.mark.django_db()
def f_user2():
    return get_user_model().objects.create(
        username="test_2",
        email="test_2@example.com",
        first_name="John",
        last_name="Tester",
    )


@pytest.fixture()
@pytest.mark.django_db()
def f_short_string_attribute():
    return Attribute.objects.create(
        name="Short string attribute",
        value_type=Attribute.TYPE_SHORT_STRING,
        identifier="short_string_attr",
        help_text="This is a short string attribute",
        generated=False,
        required=False,
    )


@pytest.fixture()
@pytest.mark.django_db()
def f_long_string_attribute():
    return Attribute.objects.create(
        name="Long string attribute",
        value_type=Attribute.TYPE_LONG_STRING,
        identifier="long_string_attr",
        help_text="This is a long string attribute",
        generated=False,
        required=False,
    )


@pytest.fixture()
@pytest.mark.django_db()
def f_user_attribute(f_user):
    return Attribute.objects.create(
        name="User attribute",
        value_type=Attribute.TYPE_USER,
        identifier="user_attr",
        help_text="This is an user attribute",
        generated=False,
        required=False,
    )


@pytest.fixture()
@pytest.mark.django_db()
def f_boolean_attribute(f_user):
    return Attribute.objects.create(
        name="Boolean attribute",
        value_type=Attribute.TYPE_BOOLEAN,
        identifier="bool_attr",
        help_text="This is an boolean attribute",
        generated=False,
        required=False,
    )


@pytest.fixture()
@pytest.mark.django_db()
def f_file_attribute(f_user):
    return Attribute.objects.create(
        name="Boolean attribute",
        value_type=Attribute.TYPE_FILE,
        identifier="file_attr",
        help_text="This is an file attribute",
        generated=False,
        required=False,
    )


@pytest.fixture()
@pytest.mark.django_db()
def f_short_string_multi_choice_attribute():
    attribute = Attribute.objects.create(
        name="Short string multiple choice attribute",
        value_type=Attribute.TYPE_SHORT_STRING,
        identifier="short_string_multi_choice_attr",
        help_text="This is a short string multiple choice attribute",
        multiple_choice=True,
    )

    AttributeValueChoice.objects.create(
        attribute=attribute, value="value1_multi", identifier="value1_multi_id", index=0
    )

    AttributeValueChoice.objects.create(
        attribute=attribute, value="value2_multi", identifier="value2_multi_id", index=1
    )

    return attribute


@pytest.fixture()
@pytest.mark.django_db()
def f_short_string_choice_attribute():
    attribute = Attribute.objects.create(
        name="Short string choice attribute",
        value_type=Attribute.TYPE_SHORT_STRING,
        identifier="short_string_choice_attr",
        help_text="This is a short string choice attribute",
        multiple_choice=False,
        generated=False,
        required=False,
    )

    AttributeValueChoice.objects.create(
        attribute=attribute, value="value1", identifier="value1_id", index=0
    )

    AttributeValueChoice.objects.create(
        attribute=attribute, value="value2", identifier="value2_id", index=1
    )

    return attribute


@pytest.fixture()
@pytest.mark.django_db()
def f_project_type():
    return ProjectType.objects.create(name="asemakaava")


@pytest.fixture()
@pytest.mark.django_db()
def f_project_subtype(f_project_type):
    return ProjectSubtype.objects.create(name="m", project_type=f_project_type, index=0)


@pytest.fixture()
@pytest.mark.django_db()
def f_project_phase_1(f_project_subtype):
    return ProjectPhase.objects.create(
        name="Käynnistys",
        color="color--tram",
        index=0,
        project_subtype=f_project_subtype,
        color_code="#009246",
    )


@pytest.fixture()
@pytest.mark.django_db()
def f_project_phase_2(f_project_subtype):
    return ProjectPhase.objects.create(
        name="OAS",
        color="color--summer",
        index=1,
        project_subtype=f_project_subtype,
        color_code="#ffc61e",
    )


@pytest.fixture()
@pytest.mark.django_db()
def f_project_section_1(f_project_phase_1):
    return ProjectPhaseSection.objects.create(
        name="Initial section", phase=f_project_phase_1, index=0
    )


@pytest.fixture()
@pytest.mark.django_db()
def f_project_section_2(f_project_phase_2):
    return ProjectPhaseSection.objects.create(
        name="Second section", phase=f_project_phase_2, index=0
    )


@pytest.fixture()
@pytest.mark.django_db()
def f_project_section_attribute_1(f_short_string_attribute, f_project_section_1):
    return ProjectPhaseSectionAttribute.objects.create(
        attribute=f_short_string_attribute,
        section=f_project_section_1,
        index=0,
    )


@pytest.fixture()
@pytest.mark.django_db()
def f_project_section_attribute_2(f_user_attribute, f_project_section_1):
    return ProjectPhaseSectionAttribute.objects.create(
        attribute=f_user_attribute, section=f_project_section_1, index=1
    )


@pytest.fixture()
@pytest.mark.django_db()
def f_project_section_attribute_3(f_long_string_attribute, f_project_section_2):
    return ProjectPhaseSectionAttribute.objects.create(
        attribute=f_long_string_attribute,
        section=f_project_section_2,
        index=2,
    )


@pytest.fixture()
@pytest.mark.django_db()
def f_project_section_attribute_4(f_short_string_choice_attribute, f_project_section_2):
    return ProjectPhaseSectionAttribute.objects.create(
        attribute=f_short_string_choice_attribute,
        section=f_project_section_2,
        index=3,
    )


@pytest.fixture()
@pytest.mark.django_db()
def f_project_section_attribute_5(f_boolean_attribute, f_project_section_2):
    return ProjectPhaseSectionAttribute.objects.create(
        attribute=f_boolean_attribute, section=f_project_section_2, index=4
    )


@pytest.fixture()
@pytest.mark.django_db()
def f_project_section_attribute_6(
    f_short_string_attribute, f_project_section_2, f_project_section_attribute_5
):
    return ProjectPhaseSectionAttribute.objects.create(
        attribute=f_short_string_attribute,
        section=f_project_section_2,
        index=5,
        relies_on=f_project_section_attribute_5,
    )


@pytest.fixture()
@pytest.mark.django_db()
def f_project_section_attribute_6_file(f_file_attribute, f_project_section_1):
    return ProjectPhaseSectionAttribute.objects.create(
        attribute=f_file_attribute, section=f_project_section_1, index=6
    )


@pytest.fixture()
@pytest.mark.django_db()
def f_project(f_user, f_project_subtype, f_project_phase_1):
    return Project.objects.create(
        user=f_user,
        name="Test project",
        identifier="test_project",
        subtype=f_project_subtype,
        phase=f_project_phase_1,
    )


@pytest.fixture()
@pytest.mark.django_db()
def f_project_with_attribute_data(f_user, f_project_subtype, f_project_phase_1):
    return Project.objects.create(
        user=f_user,
        name="Test project",
        identifier="test_project",
        subtype=f_project_subtype,
        phase=f_project_phase_1,
        attribute_data={"test": "test", "test2": "test2"},
    )


@pytest.fixture()
@pytest.mark.django_db()
def f_fieldset_attribute(attribute_factory, field_set_attribute_factory):
    fieldset_attribute = attribute_factory(
        value_type=Attribute.TYPE_FIELDSET, multiple_choice=True, required=True
    )
    field_set_attribute_factory(
        attribute_source=fieldset_attribute, attribute_target__required=True
    )
    field_set_attribute_factory(
        attribute_source=fieldset_attribute, attribute_target__required=True
    )

    return fieldset_attribute


@pytest.fixture()
@pytest.mark.django_db()
def f_comment_user1(comment_factory, f_user):
    comment = comment_factory(user=f_user)
    return comment


@pytest.fixture()
@pytest.mark.django_db()
def f_comment_user2(comment_factory, f_user2):
    comment = comment_factory(user=f_user2)
    return comment
