import pytest

from projects.models import CommonProjectPhase, Attribute
from projects.importing import AttributeImporter
from projects.importing.attribute import (
    ATTRIBUTE_NAME,
    ATTRIBUTE_PHASE_COLUMNS,
    ATTRIBUTE_TYPE,
    Phases,
)

def get_mock_excel_rows(test_objects: list):
    """ Helper for generating mock Excel rows from a list of test objects.
    Args:
        test_objects (list): A list of dictionaries representing the test objects to generate mock Excel rows for.
            Each dictionary's keys are column names, and values are the corresponding cell values.
    Returns:
        list of lists: first list is header row, subsequent lists are data rows corresponding to the test_objects values.
    """
    if not test_objects:
        return []
    header = []
    for obj in test_objects:
        for key in obj.keys():
            if key not in header:
                header.append(key)
    rows = [header]
    for obj in test_objects:
        row = [obj.get(col, None) for col in header]
        rows.append(row)
    return rows

@pytest.mark.django_db
def test_project_phases_are_created(f_project_type, f_project_subtype):
    ai = AttributeImporter()
    ai.project_type = f_project_type
    ai.create_phases(f_project_subtype)

    assert CommonProjectPhase.objects.all().count() == 6

    for i in range(1, 7):
        assert CommonProjectPhase.objects.filter(index=i).exists()


def test_set_row_indexes():
    mock_rows = get_mock_excel_rows([
        {"name": "Attribute 1", "type": "date", "editable": "Kyllä"},
        {"name": "Attribute 2", "type": "text", "editable": "Kyllä"},
        {"name": "Attribute 3", "type": "number", "editable": "Ei"},
    ])

    ai = AttributeImporter()
    ai._set_row_indexes(mock_rows[0])
    assert ai.column_index is not None
    assert ai.column_index["name"] == 0
    assert ai.column_index["type"] == 1
    assert ai.column_index["editable"] == 2

def test_check_if_row_valid():
    mock_rows = get_mock_excel_rows([
        {ATTRIBUTE_NAME: "Attribute 1", ATTRIBUTE_TYPE: "date", "editable": "Kyllä"},
        {ATTRIBUTE_NAME: "Attribute 2", "editable": "Kyllä" },
        {ATTRIBUTE_NAME: None, ATTRIBUTE_TYPE: "number", "editable": "Ei"},
    ])
    ai = AttributeImporter()
    ai._set_row_indexes(mock_rows[0])
    assert ai._check_if_row_valid(mock_rows[1]) is True
    assert ai._check_if_row_valid(mock_rows[2]) is False
    assert ai._check_if_row_valid(mock_rows[3]) is False

def test_row_part_of_fieldset():
    from projects.importing.attribute import ATTRIBUTE_FIELDSET
    mock_rows = get_mock_excel_rows([
        {"name": "Attribute 1", "type": "date", ATTRIBUTE_FIELDSET: "Fieldset 1"},
        {"name": "Attribute 2", "type": "text"},
    ])

    ai = AttributeImporter()
    ai._set_row_indexes(mock_rows[0])
    assert ai._row_part_of_fieldset(mock_rows[1]) is True
    assert ai._row_part_of_fieldset(mock_rows[2]) is False

def test_get_attribute_row_identifier():
    from projects.importing.attribute import ATTRIBUTE_IDENTIFIER, ATTRIBUTE_NAME
    mock_rows = get_mock_excel_rows([
        {ATTRIBUTE_IDENTIFIER: "single"},
        {ATTRIBUTE_IDENTIFIER: "multiple_word_identifier"},
        {ATTRIBUTE_IDENTIFIER: "with-dash"},
        {ATTRIBUTE_IDENTIFIER: "invalid identifier"},
        {ATTRIBUTE_IDENTIFIER: "v´+ery1nv<lid"},
        {ATTRIBUTE_IDENTIFIER: " whitespace "},
        {ATTRIBUTE_NAME: "Attribute 7"},
        {ATTRIBUTE_NAME: "Attribute-8"}
    ])

    ai = AttributeImporter()
    ai._set_row_indexes(mock_rows[0])
    assert ai._get_attribute_row_identifier(mock_rows[1]) == "single"
    assert ai._get_attribute_row_identifier(mock_rows[2]) == "multiple_word_identifier"
    with pytest.raises(ValueError):
        ai._get_attribute_row_identifier(mock_rows[3])
    with pytest.raises(ValueError):
        ai._get_attribute_row_identifier(mock_rows[4])
    with pytest.raises(ValueError):
        ai._get_attribute_row_identifier(mock_rows[5])
    assert ai._get_attribute_row_identifier(mock_rows[6]) == "whitespace"
    assert ai._get_attribute_row_identifier(mock_rows[7]) == "attribute_7"
    assert ai._get_attribute_row_identifier(mock_rows[8]) == "attribute_8"


def test_get_attribute_locations_parses_nested_location():
    phase_columns = ATTRIBUTE_PHASE_COLUMNS[Phases.START]
    rows = get_mock_excel_rows([
        {
            phase_columns[0]: "Section",
            phase_columns[1]: "Section ingress",
            phase_columns[2]: "1.2.3:4",
        }
    ])
    ai = AttributeImporter()
    ai._set_row_indexes(rows[0])

    assert ai._get_attribute_locations(rows[1], Phases.START.value) == {
        "label": "Section",
        "ingress": "Section ingress",
        "section_location": 10000,
        "field_location": 20000,
        "child_locations": [34000],
    }


def test_get_attribute_locations_without_child_location():
    phase_columns = ATTRIBUTE_PHASE_COLUMNS[Phases.OAS]
    rows = get_mock_excel_rows([
        {
            phase_columns[0]: "Section",
            phase_columns[1]: None,
            phase_columns[2]: "2.5",
        }
    ])
    ai = AttributeImporter()
    ai._set_row_indexes(rows[0])

    assert ai._get_attribute_locations(rows[1], Phases.OAS.value) == {
        "label": "Section",
        "ingress": None,
        "section_location": 20000,
        "field_location": 50000,
        "child_locations": [],
    }


@pytest.mark.parametrize("location", [None, "invalid"])
def test_get_attribute_locations_returns_none_for_invalid_location(location):
    phase_columns = ATTRIBUTE_PHASE_COLUMNS[Phases.REVISED_PROPOSAL]
    rows = get_mock_excel_rows([
        {
            phase_columns[0]: "Section",
            phase_columns[1]: None,
            phase_columns[2]: location,
        }
    ])
    ai = AttributeImporter()
    ai._set_row_indexes(rows[0])

    assert ai._get_attribute_locations(rows[1], Phases.REVISED_PROPOSAL.value) is None


def test_get_attribute_locations_returns_none_for_unknown_phase():
    ai = AttributeImporter()
    ai.column_index = {}

    assert ai._get_attribute_locations([], "Unknown phase") is None


@pytest.mark.parametrize(
    ("locations", "expected_index"),
    [
        ({"field_location": 20000, "child_locations": []}, 20000),
        ({"field_location": 20000, "child_locations": [34000]}, 23400),
        ({"field_location": 20000, "child_locations": [30000, 4000]}, 23040),
    ],
)
def test_calculate_index_preserves_field_and_nested_child_positions(
    locations, expected_index
):
    assert AttributeImporter.calculate_index(locations) == expected_index


@pytest.mark.parametrize(
    ("locations", "expected_index"),
    [
        ([], 0),
        (["1"], 1000),
        (["1", "2", "3"], 1203),
        (["2", "5", "1", "7"], 2508),
    ],
)
def test_calculate_deadline_index_scales_each_position_by_depth(
    locations, expected_index
):
    assert AttributeImporter.calculate_deadline_index(locations) == expected_index

def test_parse_condition():
    ai = AttributeImporter()
    assert ai._parse_condition("oas_mielipiteet_maara > 0") == {
        "variable": "oas_mielipiteet_maara",
        "operator": ">",
        "comparison_value": "0",
        "comparison_value_type": "number",
    }
    assert ai._parse_condition("jarjestetaan_luonnosvaiheessa_tilaisuus_3") == {
        "variable": "jarjestetaan_luonnosvaiheessa_tilaisuus_3",
        "operator": "==",
        "comparison_value": True,
        "comparison_value_type": "boolean",
    }
    assert ai._parse_condition("!maanomistus_kaupunki") == {
        "variable": "maanomistus_kaupunki",
        "operator": "!=",
        "comparison_value": True,
        "comparison_value_type": "boolean",
    }
    assert ai._parse_condition("kaavaprosessin_kokoluokka in [\"L\", \"XL\"]") == {
        "variable": "kaavaprosessin_kokoluokka",
        "operator": "in",
        "comparison_value": '["L", "XL"]',
        "comparison_value_type": "list<string>",
    }
    assert ai._parse_condition("kaavaprosessin_kokoluokka not in [\"S\", \"M\"]") == {
        "variable": "kaavaprosessin_kokoluokka",
        "operator": "not in",
        "comparison_value": '["S", "M"]',
        "comparison_value_type": "list<string>",
    }
    assert ai._parse_condition("lautakunta_paatti_ehdotus == \"paatos_kaavaehdotuksesta_asia_jai_poydalle\"") == {
        "variable": "lautakunta_paatti_ehdotus",
        "operator": "==",
        "comparison_value": "paatos_kaavaehdotuksesta_asia_jai_poydalle",
        "comparison_value_type": "string",
    }

def test_parse_autofill_rule():
    ai = AttributeImporter()

    # Test rule for autofilling a value with a simple "ei" condition
    assert ai._parse_autofill_rule("ei", Attribute.TYPE_SHORT_STRING) == None

    # Test rule for autofilling a hardcoded value
    assert ai._parse_autofill_rule("{% if !maanomistus_kaupunki %} 0 {% endif %}", Attribute.TYPE_INTEGER) == [
        {
            "variables": [],
            "conditions": [
                {
                    "variable": "maanomistus_kaupunki",
                    "operator": "!=",
                    "comparison_value": True,
                    "comparison_value_type": "boolean",
                }
            ],
            "then_branch": "0",
            "else_branch": None
        }
    ]
    # Test rule for autofilling a value based on a variable
    assert ai._parse_autofill_rule("{{milta_ulkopuolisilta_pyydetaan_lausunto}} {% if milta_ulkopuolisilta_pyydetaan_lausunto %} {% endif %}", Attribute.TYPE_CHOICE) == [
        {
            "variables": ["milta_ulkopuolisilta_pyydetaan_lausunto"],
            "conditions": [
                {
                    "variable": "milta_ulkopuolisilta_pyydetaan_lausunto",
                    "operator": "==",
                    "comparison_value": True,
                    "comparison_value_type": "boolean",
                }
            ],
            "then_branch": "",
            "else_branch": None
        }
    ]
    # Test rule for autofilling a value based on multiple conditions
    assert ai._parse_autofill_rule("{% if periaatteet_mielipiteet_maara > 0 or oas_mielipiteet_maara > 0 %} kyllä {% endif %}",
        Attribute.TYPE_CHOICE
    ) == [
        {
            "variables": [],
            "conditions": [
                {
                    "variable": "periaatteet_mielipiteet_maara",
                    "operator": ">",
                    "comparison_value": '0',
                    "comparison_value_type": "number",
                },
            ],
            "then_branch": "kylla",
            "else_branch": None
        },
        {
            "variables": [],
            "conditions": [
                {
                    "variable": "oas_mielipiteet_maara",
                    "operator": ">",
                    "comparison_value": '0',
                    "comparison_value_type": "number",
                },
            ],
            "then_branch": "kylla",
            "else_branch": None
        },
    ]
    # Test boolean conversion kylla/ei to True/False
    assert ai._parse_autofill_rule("{% if condition %} kyllä {% endif %}", Attribute.TYPE_BOOLEAN) == [
        {
            "variables": [],
            "conditions": [
                {
                    "variable": "condition",
                    "operator": "==",
                    "comparison_value": True,
                    "comparison_value_type": "boolean",
                }
            ],
            "then_branch": True,
            "else_branch": None
        }
    ]
    assert ai._parse_autofill_rule("{% if !condition %} ei {% endif %}", Attribute.TYPE_BOOLEAN) == [
        {
            "variables": [],
            "conditions": [
                {
                    "variable": "condition",
                    "operator": "!=",
                    "comparison_value": True,
                    "comparison_value_type": "boolean",
                }
            ],
            "then_branch": False,
            "else_branch": None
        }
    ]

def test_parse_autofill_readonly():
    # Tests parsing rules for "is autofilled column editable"- column
    ai = AttributeImporter()
    assert ai._parse_autofill_readonly("ei") == True
    assert ai._parse_autofill_readonly("Automaattiseti muodostunutta tietoa ei voi muokata") == True
    assert ai._parse_autofill_readonly("kyllä") == False
    assert ai._parse_autofill_readonly("") == False


def test_get_attribute_locations():
    pass