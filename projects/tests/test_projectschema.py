import pytest
from django.contrib.auth import get_user_model

from projects.models import Attribute
from projects.serializers.projectschema import (
    AttributeSchemaSerializer,
    ProjectPhaseSchemaSerializer,
    ProjectSectionSchemaSerializer,
)


@pytest.mark.django_db(transaction=True)
class TestAttributeSchemaSerializer:
    @pytest.mark.parametrize(
        "attribute, instanceof",
        [
            (pytest.lazy_fixture("f_user_attribute"), list),
            (pytest.lazy_fixture("f_short_string_choice_attribute"), list),
            (Attribute(value_type=Attribute.TYPE_SHORT_STRING), type(None)),
        ],
    )
    def test_get_choices(self, attribute, instanceof):
        assert isinstance(AttributeSchemaSerializer.get_choices(attribute), instanceof)

    def test__get_foreign_key_choices(self, f_user):
        choice_data = {
            "model": get_user_model(),
            "filters": {},
            "label_format": "{instance.first_name} {instance.last_name}",
        }

        choices = AttributeSchemaSerializer._get_foreign_key_choices(choice_data)
        assert choices == [
            {
                "label": "{} {}".format(f_user.first_name, f_user.last_name),
                "value": f_user.pk,
            }
        ]

        choice_data["model"] = Attribute
        choices = AttributeSchemaSerializer._get_foreign_key_choices(choice_data)
        assert choices == []

    def test__get_attribute_choices(
        self, f_short_string_attribute, f_short_string_choice_attribute
    ):
        asserted_value_choices = f_short_string_choice_attribute.value_choices.all()
        asserted_choices = []
        for choice in asserted_value_choices:
            asserted_choices.append({"label": choice.value, "value": choice.identifier})

        choices = AttributeSchemaSerializer._get_attribute_choices(
            f_short_string_choice_attribute
        )
        assert choices == asserted_choices

        # Having no choices should return an empty list
        choices = AttributeSchemaSerializer._get_attribute_choices(
            f_short_string_attribute
        )
        assert choices == []


@pytest.mark.django_db(transaction=True)
class TestProjectSectionSchemaSerializer:
    @pytest.mark.parametrize(
        "matrix_data, max_index, result",
        [({"index": 2}, 1, 1), ({"index": 2}, 4, 1), ({"index": 2}, 2, 1)],
    )
    def test__get_matrix_attribute_index(self, matrix_data, max_index, result):
        assert (
            ProjectSectionSchemaSerializer._get_matrix_attribute_index(
                matrix_data, max_index
            )
            == result
        )

    def test__sort_matrices(self):
        matrices = {
            1: {
                "fields": [
                    {"row": 3, "column": 3},
                    {"row": 2, "column": 2},
                    {"row": 3, "column": 1},
                    {"row": 2, "column": 3},
                    {"row": 3, "column": 2},
                    {"row": 2, "column": 1},
                    {"row": 1, "column": 1},
                    {"row": 1, "column": 2},
                    {"row": 1, "column": 3},
                ]
            }
        }

        sorted_matrices = {
            1: {
                "fields": [
                    {"row": 1, "column": 1},
                    {"row": 1, "column": 2},
                    {"row": 1, "column": 3},
                    {"row": 2, "column": 1},
                    {"row": 2, "column": 2},
                    {"row": 2, "column": 3},
                    {"row": 3, "column": 1},
                    {"row": 3, "column": 2},
                    {"row": 3, "column": 3},
                ]
            }
        }

        ProjectSectionSchemaSerializer._sort_matrices(matrices)
        assert matrices == sorted_matrices


@pytest.mark.parametrize(
    "value_type", [(Attribute.TYPE_SHORT_STRING, Attribute.TYPE_FIELDSET)]
)
@pytest.mark.django_db()
def test_fieldset_schema_renders(
    attribute_factory,
    field_set_attribute_factory,
    project_phase_section_attribute_factory,
    value_type,
):
    fieldset_attribute = attribute_factory(value_type=value_type, multiple_choice=True)
    attr1 = field_set_attribute_factory(attribute_source=fieldset_attribute)
    attr2 = field_set_attribute_factory(attribute_source=fieldset_attribute)

    ppsa = project_phase_section_attribute_factory(attribute=fieldset_attribute)

    phase = ppsa.section.phase
    schema = ProjectPhaseSchemaSerializer(phase).data

    fields_schema = schema["sections"][0]["fields"]
    assert len(fields_schema) == 1

    fieldset_field = fields_schema[0]

    if value_type == Attribute.TYPE_FIELDSET:
        # Fieldset includes related attributes in the correct order
        assert fieldset_field["type"] == Attribute.TYPE_FIELDSET
        assert fieldset_field["multiple_choice"] is True

        assert len(fieldset_field["fieldset_attributes"]) == 2

        assert (
            fieldset_field["fieldset_attributes"][0]["name"]
            == attr1.attribute_target.identifier
        )
        assert (
            fieldset_field["fieldset_attributes"][1]["name"]
            == attr2.attribute_target.identifier
        )

    elif value_type == Attribute.TYPE_SHORT_STRING:
        # Non-fieldset attributes ignore possibly related fields
        assert fieldset_field["type"] == Attribute.TYPE_SHORT_STRING
        assert len(fieldset_field["fieldset_attributes"]) == 0
