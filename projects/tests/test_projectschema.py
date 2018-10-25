import pytest
from django.contrib.auth import get_user_model

from projects.models import Attribute, ProjectPhaseSectionAttribute
from projects.serializers.projectschema import (
    VALUE_TYPE_MAP,
    ProjectSectionAttributeSchemaSerializer,
)


@pytest.mark.django_db(transaction=True)
class TestProjectSectionAttributeSchemaSerializer:
    def test_get_type(self):
        for attribute_type, new_attribute_type in VALUE_TYPE_MAP.items():
            attribute = Attribute(value_type=attribute_type)
            section_attribute = ProjectPhaseSectionAttribute(attribute=attribute)
            returned_type = ProjectSectionAttributeSchemaSerializer.get_type(
                section_attribute
            )
            assert returned_type == new_attribute_type

    @pytest.mark.parametrize(
        "section_attribute, instanceof",
        [
            (pytest.lazy_fixture("f_project_section_attribute_2"), list),
            (pytest.lazy_fixture("f_project_section_attribute_4"), list),
            (
                ProjectPhaseSectionAttribute(
                    attribute=Attribute(value_type=Attribute.TYPE_SHORT_STRING)
                ),
                type(None),
            ),
        ],
    )
    def test_get_choices(self, section_attribute, instanceof):
        assert isinstance(
            ProjectSectionAttributeSchemaSerializer.get_choices(section_attribute),
            instanceof,
        )

    def test__get_foreign_key_choices(self, f_user):
        choice_data = {
            "model": get_user_model(),
            "filters": {},
            "label_format": "{instance.first_name} {instance.last_name}",
        }

        choices = ProjectSectionAttributeSchemaSerializer._get_foreign_key_choices(
            choice_data
        )
        assert choices == [
            {
                "label": "{} {}".format(f_user.first_name, f_user.last_name),
                "value": f_user.pk,
            }
        ]

        choice_data["model"] = Attribute
        choices = ProjectSectionAttributeSchemaSerializer._get_foreign_key_choices(
            choice_data
        )
        assert choices == []

    def test__get_section_attribute_choices(
        self, f_project_section_attribute_1, f_project_section_attribute_4
    ):
        asserted_value_choices = (
            f_project_section_attribute_4.attribute.value_choices.all()
        )
        asserted_choices = []
        for choice in asserted_value_choices:
            asserted_choices.append({"label": choice.value, "value": choice.identifier})

        choices = ProjectSectionAttributeSchemaSerializer._get_section_attribute_choices(
            f_project_section_attribute_4
        )
        assert choices == asserted_choices

        choices = ProjectSectionAttributeSchemaSerializer._get_section_attribute_choices(
            f_project_section_attribute_1
        )
        assert choices == []
