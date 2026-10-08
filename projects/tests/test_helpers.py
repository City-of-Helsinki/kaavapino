from types import SimpleNamespace

import pytest

from projects.models import (
	Attribute,
	AttributeAutoValue,
	AttributeAutoValueMapping,
	FieldSetAttribute,
)
from projects.helpers import (
	check_visibility,
	check_format_date,
	format_choices,
	get_attribute_data,
	get_attribute_data_filtered_response,
	get_attribute_lock_data,
	get_file_type,
	get_fieldset_path,
	get_flat_attribute_data,
	safe_bool,
	safe_float,
	sanitize_attribute_data_filter_result,
	set_automatic_attributes,
	set_attribute_data,
)


@pytest.mark.parametrize(
	("stored_value", "expected"),
	[
		(True, True),
		("true", True),
		("FALSE", False),
		("not empty", True),
		(None, False),
	],
)
def test_boolean_visibility_conditions_interpret_stored_values_consistently(
	stored_value, expected
):
	attribute = SimpleNamespace(
		identifier="conditional_attribute",
		visibility_conditions=[
			{
				"operator": "==",
				"variable": "show_attribute",
				"comparison_value_type": "boolean",
				"comparison_value": True,
			}
		],
	)
	project = SimpleNamespace(attribute_data={"show_attribute": stored_value})

	assert check_visibility(project, attribute) is expected


def test_visibility_succeeds_when_a_later_alternative_condition_matches():
	attribute = SimpleNamespace(
		identifier="conditional_attribute",
		visibility_conditions=[
			{
				"operator": "==",
				"variable": "first_flag",
				"comparison_value_type": "boolean",
				"comparison_value": True,
			},
			{
				"operator": "==",
				"variable": "second_flag",
				"comparison_value_type": "boolean",
				"comparison_value": True,
			},
		],
	)
	project = SimpleNamespace(
		attribute_data={"first_flag": False, "second_flag": True}
	)

	assert check_visibility(project, attribute) is True


@pytest.mark.django_db
def test_filtered_response_excludes_hidden_fields_and_deleted_fieldset_entries(f_project):
	visible = Attribute.objects.create(
		name="Visible text",
		identifier="visible_text",
		value_type=Attribute.TYPE_SHORT_STRING,
		api_visibility=True,
	)
	hidden_by_api = Attribute.objects.create(
		name="Private text",
		identifier="private_text",
		value_type=Attribute.TYPE_SHORT_STRING,
		api_visibility=False,
	)
	ignored = Attribute.objects.create(
		name="Ignored text",
		identifier="ignored_text",
		value_type=Attribute.TYPE_SHORT_STRING,
		api_visibility=True,
	)
	conditional = Attribute.objects.create(
		name="Conditional text",
		identifier="conditional_text",
		value_type=Attribute.TYPE_SHORT_STRING,
		api_visibility=True,
		visibility_conditions=[
			{
				"operator": "==",
				"variable": "show_conditional",
				"comparison_value_type": "boolean",
				"comparison_value": True,
			}
		],
	)
	fieldset = Attribute.objects.create(
		name="People",
		identifier="people_fieldset",
		value_type=Attribute.TYPE_FIELDSET,
		api_visibility=True,
	)
	fieldset_visible = Attribute.objects.create(
		name="Person name",
		identifier="person_name",
		value_type=Attribute.TYPE_SHORT_STRING,
		api_visibility=True,
	)
	fieldset_hidden = Attribute.objects.create(
		name="Private person detail",
		identifier="person_private_detail",
		value_type=Attribute.TYPE_SHORT_STRING,
		api_visibility=False,
	)

	f_project.attribute_data = {
		"visible_text": "visible value",
		"private_text": "private value",
		"ignored_text": "ignored value",
		"conditional_text": "should not be exported",
		"show_conditional": False,
		"people_fieldset": [
			{"person_name": "Current person", "person_private_detail": "secret"},
			{"person_name": "Deleted person", "_deleted": True},
		],
	}
	f_project.save(update_fields=["attribute_data"])
	attributes = {
		attribute.identifier: attribute
		for attribute in [
			visible,
			hidden_by_api,
			ignored,
			conditional,
			fieldset,
			fieldset_visible,
			fieldset_hidden,
		]
	}

	response = get_attribute_data_filtered_response(
		attributes=attributes,
		value_choices={},
		generated_attributes=[],
		ignored={ignored.id},
		project=f_project,
		use_cached=False,
	)

	assert response["visible_text"] == "visible value"
	assert response["people_fieldset"] == [{"person_name": "Current person"}]
	assert "private_text" not in response
	assert "ignored_text" not in response
	assert "conditional_text" not in response


@pytest.mark.django_db
def test_fieldset_path_returns_parents_from_outermost_to_innermost():
	outer = Attribute.objects.create(
		name="Outer fieldset",
		identifier="outer_fieldset",
		value_type=Attribute.TYPE_FIELDSET,
	)
	inner = Attribute.objects.create(
		name="Inner fieldset",
		identifier="inner_fieldset",
		value_type=Attribute.TYPE_FIELDSET,
	)
	leaf = Attribute.objects.create(
		name="Leaf value",
		identifier="leaf_value",
		value_type=Attribute.TYPE_SHORT_STRING,
	)
	FieldSetAttribute.objects.create(attribute_source=outer, attribute_target=inner)
	FieldSetAttribute.objects.create(attribute_source=inner, attribute_target=leaf)

	assert get_fieldset_path(leaf, cached=False) == [outer, inner]


@pytest.mark.django_db
def test_nested_attribute_data_helpers_round_trip_values_at_distinct_fieldset_indices():
	fieldset = Attribute.objects.create(
		name="People",
		identifier="people",
		value_type=Attribute.TYPE_FIELDSET,
	)
	name = Attribute.objects.create(
		name="Name",
		identifier="name",
		value_type=Attribute.TYPE_SHORT_STRING,
	)
	data = {}

	set_attribute_data(data, [fieldset, 0, name], "First person")
	set_attribute_data(data, [fieldset, 1, name], "Second person")

	assert data == {
		"people": [
			{"name": "First person"},
			{"name": "Second person"},
		]
	}
	assert get_attribute_data([fieldset, 1, name], data) == "Second person"


@pytest.mark.django_db
def test_flat_attribute_data_collects_values_from_repeated_fieldset_entries(monkeypatch):
	fieldset = Attribute.objects.create(
		name="People",
		identifier="flat_people",
		value_type=Attribute.TYPE_FIELDSET,
	)
	name = Attribute.objects.create(
		name="Name",
		identifier="flat_person_name",
		value_type=Attribute.TYPE_SHORT_STRING,
	)
	age = Attribute.objects.create(
		name="Age",
		identifier="flat_person_age",
		value_type=Attribute.TYPE_INTEGER,
	)
	FieldSetAttribute.objects.create(attribute_source=fieldset, attribute_target=name)
	FieldSetAttribute.objects.create(attribute_source=fieldset, attribute_target=age)
	data = {
		"pinonumero": "helpers-flat-test-001",
		"flat_people": [
			{"flat_person_name": "Ada", "flat_person_age": 36},
			{"flat_person_name": "Grace", "flat_person_age": 85},
		],
	}

    # Ensure that the cache is bypassed for this test
	monkeypatch.setattr(
		"projects.helpers.cache.get_or_set",
		lambda cache_key, default: default,
	)

	flat = get_flat_attribute_data(data, {})

	assert flat["flat_person_name"] == ["Ada", "Grace"]
	assert flat["flat_person_age"] == [36, 85]
	assert flat["pinonumero"] == ["helpers-flat-test-001"]


@pytest.mark.django_db
def test_automatic_attribute_uses_matching_scalar_key_mapping():
	key_attribute = Attribute.objects.create(
		name="Selected role",
		identifier="automatic_role_key",
		value_type=Attribute.TYPE_CHOICE,
	)
	value_attribute = Attribute.objects.create(
		name="Contact person",
		identifier="automatic_contact_person",
		value_type=Attribute.TYPE_SHORT_STRING,
	)
	auto_value = AttributeAutoValue.objects.create(
		key_attribute=key_attribute,
		value_attribute=value_attribute,
	)
	AttributeAutoValueMapping.objects.create(
		auto_attr=auto_value,
		key_str="planning_contact",
		value_str="Ada Lovelace",
	)
	attribute_data = {"automatic_role_key": "planning_contact"}

	set_automatic_attributes(attribute_data)

	assert attribute_data == {
		"automatic_role_key": "planning_contact",
		"automatic_contact_person": "Ada Lovelace",
	}


@pytest.mark.django_db
@pytest.mark.parametrize("key", ["unmapped_role", None, ""])
def test_automatic_attribute_leaves_existing_value_when_key_has_no_mapping(key):
	key_attribute = Attribute.objects.create(
		name="Selected role",
		identifier="automatic_missing_role_key",
		value_type=Attribute.TYPE_CHOICE,
	)
	value_attribute = Attribute.objects.create(
		name="Contact person",
		identifier="automatic_existing_contact",
		value_type=Attribute.TYPE_SHORT_STRING,
	)
	AttributeAutoValue.objects.create(
		key_attribute=key_attribute,
		value_attribute=value_attribute,
	)
	attribute_data = {
		"automatic_missing_role_key": key,
		"automatic_existing_contact": "Manually entered value",
	}

	set_automatic_attributes(attribute_data)

	assert attribute_data["automatic_existing_contact"] == "Manually entered value"


@pytest.mark.django_db
def test_automatic_attribute_maps_each_repeated_fieldset_entry_independently():
	fieldset = Attribute.objects.create(
		name="People",
		identifier="automatic_people",
		value_type=Attribute.TYPE_FIELDSET,
	)
	key_attribute = Attribute.objects.create(
		name="Role",
		identifier="automatic_person_role",
		value_type=Attribute.TYPE_CHOICE,
	)
	value_attribute = Attribute.objects.create(
		name="Contact",
		identifier="automatic_person_contact",
		value_type=Attribute.TYPE_SHORT_STRING,
	)
	FieldSetAttribute.objects.create(
		attribute_source=fieldset,
		attribute_target=key_attribute,
	)
	FieldSetAttribute.objects.create(
		attribute_source=fieldset,
		attribute_target=value_attribute,
	)
	auto_value = AttributeAutoValue.objects.create(
		key_attribute=key_attribute,
		value_attribute=value_attribute,
	)
	AttributeAutoValueMapping.objects.create(
		auto_attr=auto_value,
		key_str="planner",
		value_str="Ada",
	)
	AttributeAutoValueMapping.objects.create(
		auto_attr=auto_value,
		key_str="reviewer",
		value_str="Grace",
	)
	attribute_data = {
		"automatic_people": [
			{"automatic_person_role": "planner"},
			{"automatic_person_role": "reviewer"},
		]
	}

	set_automatic_attributes(attribute_data)

	assert attribute_data["automatic_people"] == [
		{
			"automatic_person_role": "planner",
			"automatic_person_contact": "Ada",
		},
		{
			"automatic_person_role": "reviewer",
			"automatic_person_contact": "Grace",
		},
	]


def test_sanitizer_aggregates_applicant_fieldset_and_removes_source():
	applicants = SimpleNamespace(
		identifier="hakija_fieldset",
		value_type=Attribute.TYPE_FIELDSET,
	)
	attribute_data = {
		"hakija_fieldset": [
			{
				"hakija_yritys": "Example Ltd",
				"hakijalta_perittava_maksu_oas": "12.5",
				"hakijalta_perittava_maksu_ehdotus": "not a number",
				"hakijalta_perittava_maksu": 3,
				"laskutuspyynto_oas": "2026-02-03",
			},
			{
				"hakijan_etunimi_yksityishenkilo": "Ada",
				"hakijan_sukunimi_yksityishenkilo": "Lovelace",
				"hakijalta_perittava_maksu_oas": "7.5",
				"hakijalta_perittava_maksu_ehdotus": "2",
				"hakijalta_perittava_maksu": "4",
				"laskutuspyynto_oas": None,
				"laskutuspyynto_ehdotus": "2026-12-01",
			},
		]
	}

	result = sanitize_attribute_data_filter_result(
		{"hakija_fieldset": applicants},
		attribute_data,
	)

	assert result == {
		"hakija_taho": "Hakija yritys: Example Ltd; Hakija yksityishenkilö",
		"hakijalta_perittava_maksu_oas": 20,
		"hakijalta_perittava_maksu_ehdotus": 2,
		"hakijalta_perittava_maksu": 7,
		"kaavaprojekti_maksu_yhteensa": 29,
		"laskutuspyynto_oas": "03.02.2026",
		"laskutuspyynto_ehdotus": "01.12.2026",
		"laskutuspyynto_hyvaksymisen_jalkeen": "",
	}


@pytest.mark.parametrize(
	("value_type", "value", "expected"),
	[
		(Attribute.TYPE_DATE, "2026-10-05", "05.10.2026"),
		(Attribute.TYPE_DATE, "not-a-date", "not-a-date"),
		(Attribute.TYPE_CHOICE, ["small", "large"], "small; large"),
		(Attribute.TYPE_CHOICE, "small", "small"),
	],
)
def test_sanitizer_formats_date_and_choice_values(value_type, value, expected):
	attribute = SimpleNamespace(identifier="sanitized_value", value_type=value_type)

	result = sanitize_attribute_data_filter_result(
		{"sanitized_value": attribute},
		{"sanitized_value": value},
	)

	assert result["sanitized_value"] == expected


def test_sanitizer_joins_nonempty_values_in_supported_staff_fieldsets():
	staff = SimpleNamespace(
		identifier="kaavoittaja_fieldset",
		value_type=Attribute.TYPE_FIELDSET,
	)
	attribute_data = {
		"kaavoittaja_fieldset": [
			{"name": "Ada", "role": "Planner", "empty": ""},
			{"name": "Grace", "role": None},
		]
	}

	result = sanitize_attribute_data_filter_result(
		{"kaavoittaja_fieldset": staff},
		attribute_data,
	)

	assert result["kaavoittaja_fieldset"] == "Ada, Planner; Grace"


@pytest.mark.parametrize(
	("filename", "expected"),
	[
		("plan.docx", "docx"),
		("archive.backup.xlsx", "xlsx"),
		("README", "README"),
		("hidden.", ""),
	],
)
def test_get_file_type_returns_final_filename_component(filename, expected):
	assert get_file_type(filename) == expected


@pytest.mark.parametrize(
	("identifier", "expected"),
	[
		(
			"person_fieldset[2]",
			{
				"fieldset_attribute_identifier": "person_fieldset",
				"fieldset_attribute_index": "2",
			},
		),
		("project_name", {"attribute_identifier": "project_name"}),
		(
			"person_fieldset[2][3]",
			{
				"fieldset_attribute_identifier": "person_fieldset",
				"fieldset_attribute_index": "2",
			},
		),
	],
)
def test_get_attribute_lock_data_parses_regular_and_fieldset_identifiers(
	identifier, expected
):
	assert get_attribute_lock_data(identifier) == expected


@pytest.mark.parametrize(
	("date_value", "expected"),
	[
		("2026-10-05", "05.10.2026"),
		("not-a-date", "not-a-date"),
		("2026-02-30", "2026-02-30"),
		(None, None),
	],
)
def test_check_format_date_formats_iso_dates_and_preserves_invalid_values(
	date_value, expected
):
	assert check_format_date(date_value) == expected


@pytest.mark.parametrize(
	("value", "expected"),
	[
		(3, 3.0),
		("-1.25", -1.25),
		("invalid", 0.0),
		(None, 0.0),
	],
)
def test_safe_float_returns_zero_for_non_numeric_values(value, expected):
	assert safe_float(value) == expected


@pytest.mark.parametrize(
	("value", "expected"),
	[
		(True, True),
		(False, False),
		("TRUE", True),
		("false", False),
		("2026-10-05", True),
		("", False),
		(None, True),
	],
)
def test_safe_bool_handles_boolean_strings_and_truthy_nonempty_values(value, expected):
	assert safe_bool(value) is expected


def test_format_choices_translates_nested_lists_and_preserves_unknown_values():
	choices = {
		"small": SimpleNamespace(value="Small"),
		"large": SimpleNamespace(value="Large"),
	}

	assert format_choices(choices, ["small", ["large", "unknown"]]) == (
		"Small; Large; unknown"
	)
