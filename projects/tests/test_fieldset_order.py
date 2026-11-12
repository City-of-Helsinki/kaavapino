import pytest
from django.http import HttpRequest
from rest_framework.request import Request

from projects.exporting.document import sort_fieldset_display_items
from projects.serializers.section import create_section_serializer


def _ordered_indices(fieldset_value):
    display_items = [{"index": index} for index in range(len(fieldset_value))]
    sort_fieldset_display_items(display_items, fieldset_value)
    return [item["index"] for item in display_items]


@pytest.mark.parametrize(
    ("fieldset_value", "expected"),
    [
        pytest.param([], [], id="empty fieldset"),
        pytest.param(
            [{"name": "a"}, {"name": "b"}, {"name": "c"}],
            [0, 1, 2],
            id="legacy rows without _order keep array order",
        ),
        pytest.param(
            [{"name": "a", "_order": 2}, {"name": "b", "_order": 0}, {"name": "c", "_order": 1}],
            [1, 2, 0],
            id="reordered rows follow _order instead of array index",
        ),
        pytest.param(
            [{"name": "a", "_order": 1}, {"name": "b", "_order": 0}, {"name": "new"}],
            [1, 0, 2],
            id="row added after reordering has no _order and ends up last",
        ),
        pytest.param(
            [
                {"name": "a", "_order": 1},
                {"name": None, "_deleted": True},
                {"name": "c", "_order": 0},
                {"name": "new"},
            ],
            [2, 0, 1, 3],
            id="tombstone without _order does not displace ordered rows",
        ),
        pytest.param(
            [{"name": "a", "_order": None}, {"name": "b", "_order": "0"}, {"name": "c", "_order": True}],
            [0, 1, 2],
            id="invalid _order types fall back to index",
        ),
        pytest.param(
            [{"name": "a", "_order": 1}, {"name": "b"}, {"name": "c", "_order": 1}],
            [0, 1, 2],
            id="ties are broken by original index",
        ),
    ],
)
def test_fieldset_rows_are_exported_in_display_order(fieldset_value, expected):
    assert _ordered_indices(fieldset_value) == expected


def test_display_items_appended_for_file_only_rows_are_sorted_into_place():
    fieldset_value = [
        {"name": "a", "_order": 2},
        {"_order": 0},  # row containing only an image, appended by _set_fieldset_path
        {"name": "c", "_order": 1},
    ]
    display_items = [{"index": 0, "name": "a"}, {"index": 2, "name": "c"}, {"index": 1}]

    sort_fieldset_display_items(display_items, fieldset_value)

    assert [item["index"] for item in display_items] == [1, 2, 0]


def test_display_items_sorting_tolerates_missing_or_short_raw_data():
    display_items = [{"index": 3}, {"index": 0}]

    sort_fieldset_display_items(display_items, None)
    assert [item["index"] for item in display_items] == [0, 3]

    sort_fieldset_display_items(display_items, [{"_order": 5}])
    assert [item["index"] for item in display_items] == [3, 0]


@pytest.fixture()
def fieldset_section(f_fieldset_attribute, project, project_phase_section_attribute_factory):
    ppsa = project_phase_section_attribute_factory(attribute=f_fieldset_attribute)
    project.phase = ppsa.section.phase
    project.save()
    return ppsa.section


def _section_serializer(section):
    return create_section_serializer(section, {"request": Request(HttpRequest())})


@pytest.mark.django_db()
def test_section_serializer_keeps_fieldset_order_and_omits_it_for_legacy_rows(
    f_fieldset_attribute, fieldset_section
):
    field1, field2 = f_fieldset_attribute.fieldset_attributes.all()[:2]
    identifier = f_fieldset_attribute.identifier
    data = {
        identifier: [
            {field1.identifier: "AAA", field2.identifier: "BBB", "_order": 1},
            {field1.identifier: "CCC", field2.identifier: "DDD", "_order": 0},
            {field1.identifier: "EEE", field2.identifier: "FFF"},
        ]
    }

    serializer = _section_serializer(fieldset_section)(data=data)

    assert serializer.is_valid(), serializer.errors
    rows = serializer.validated_data[identifier]
    assert rows[0]["_order"] == 1
    assert rows[1]["_order"] == 0
    assert "_order" not in rows[2]


@pytest.mark.django_db()
@pytest.mark.parametrize("invalid_order", [-1, "first", 1.5])
def test_section_serializer_rejects_invalid_fieldset_order(
    f_fieldset_attribute, fieldset_section, invalid_order
):
    field1, field2 = f_fieldset_attribute.fieldset_attributes.all()[:2]
    data = {
        f_fieldset_attribute.identifier: [
            {field1.identifier: "AAA", field2.identifier: "BBB", "_order": invalid_order},
        ]
    }

    assert not _section_serializer(fieldset_section)(data=data).is_valid()


@pytest.mark.django_db()
def test_fieldset_order_and_tombstones_survive_attribute_data_round_trip(
    f_fieldset_attribute, project, fieldset_section
):
    field1, field2 = f_fieldset_attribute.fieldset_attributes.all()[:2]
    identifier = f_fieldset_attribute.identifier

    project.update_attribute_data({
        identifier: [
            {field1.identifier: "AAA", field2.identifier: "BBB", "_order": 1},
            {field1.identifier: None, "_deleted": True},
            {field1.identifier: "CCC", field2.identifier: "DDD", "_order": 0},
        ]
    })
    project.save()
    project.refresh_from_db()

    stored = project.attribute_data[identifier]
    assert [row.get("_order") for row in stored] == [1, None, 0]
    assert stored[1]["_deleted"] is True

    loaded = project.get_attribute_data()[identifier]
    assert [row.get("_order") for row in loaded] == [1, None, 0]
