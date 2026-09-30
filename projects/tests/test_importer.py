import pytest

from projects.importing import AttributeImporter
from projects.models import CommonProjectPhase

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
    from projects.importing.attribute import ATTRIBUTE_NAME, ATTRIBUTE_TYPE
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


