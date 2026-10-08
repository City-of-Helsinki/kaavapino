import pytest

from projects.importing.deadline import (
	DEADLINE_ABBREVIATION,
	DEADLINE_ATTRIBUTE_CONDITION,
	DEADLINE_ATTRIBUTE_IDENTIFIER,
	DEADLINE_CALCULATION_DATE_TYPE,
	DEADLINE_CONFIRMATION_ATTRIBUTE_IDENTIFIER,
	DEADLINE_CREATED_AT_ATTRIBUTE_FIELD_VALUE,
	DEADLINE_DATE_TYPE,
	DEADLINE_ERROR_DATE_TYPE_MISMATCH,
	DEADLINE_ERROR_MIN_DISTANCE_PREV,
	DEADLINE_ERROR_PAST_DUE,
	DEADLINE_GROUP,
	DEADLINE_INITIAL_CALCULATIONS,
	DEADLINE_MINIMUM_DISTANCE,
	DEADLINE_PHASE,
	DEADLINE_TYPE,
	DEADLINE_UPDATE_CALCULATIONS,
	DEADLINE_WARNING_MIN_DISTANCE_NEXT,
	DeadlineImporter,
)
from projects.models import (
	Attribute,
	DateCalculation,
	DateType,
	Deadline,
	DeadlineDistance,
	DeadlineDistanceConditionAttribute,
)


def relation_row(**values):
	columns = [
		DEADLINE_ABBREVIATION,
		DEADLINE_ATTRIBUTE_CONDITION,
		DEADLINE_CALCULATION_DATE_TYPE,
		DEADLINE_INITIAL_CALCULATIONS,
		DEADLINE_UPDATE_CALCULATIONS,
		DEADLINE_MINIMUM_DISTANCE,
	]
	row_values = {column: None for column in columns}
	row_values.update(values)
	return columns, [row_values[column] for column in columns]


def deadline_row(**values):
	columns = [
		DEADLINE_ATTRIBUTE_IDENTIFIER,
		DEADLINE_CONFIRMATION_ATTRIBUTE_IDENTIFIER,
		DEADLINE_ABBREVIATION,
		DEADLINE_TYPE,
		DEADLINE_DATE_TYPE,
		DEADLINE_ATTRIBUTE_CONDITION,
		DEADLINE_PHASE,
		DEADLINE_ERROR_PAST_DUE,
		DEADLINE_ERROR_DATE_TYPE_MISMATCH,
		DEADLINE_ERROR_MIN_DISTANCE_PREV,
		DEADLINE_WARNING_MIN_DISTANCE_NEXT,
		DEADLINE_GROUP,
	]
	row_values = {column: None for column in columns}
	row_values.update(values)
	return columns, [row_values[column] for column in columns]


def create_deadline(subtype, phase, abbreviation):
	return Deadline.objects.create(
		abbreviation=abbreviation,
		subtype=subtype,
		phase=phase,
	)


def test_parse_conditions_returns_empty_for_plain_calculations():
	importer = DeadlineImporter()

	assert importer._parse_conditions("E5.3") == []
	assert importer._parse_conditions("P2 + 13") == []


def test_parse_conditions_extracts_adjacent_subtype_branches():
	importer = DeadlineImporter()
	rule = (
		'{% if kaavaprosessin_kokoluokka == "XL" %}U1 + 55{% endif %} '
		'{% if kaavaprosessin_kokoluokka in ["M", "S"] %}'
		'U1 + 40{% endif %}'
	)

	assert importer._parse_conditions(rule) == [
		(["kaavaprosessin_kokoluokka == \"XL\""], "U1 + 55"),
		(["kaavaprosessin_kokoluokka in [\"M\", \"S\"]"], "U1 + 40"),
	]


def test_parse_conditions_splits_or_but_preserves_and():
	importer = DeadlineImporter()
	rule = (
		"{% if first_condition or second_condition %}A1 + 5{% endif %}"
		"{% if positive_condition and other_condition %}B1 + 10{% endif %}"
		"{% if !negative_condition and other_condition %}C1 + 15{% endif %}"
	)

	assert importer._parse_conditions(rule) == [
		(["first_condition", "second_condition"], "A1 + 5"),
		(["positive_condition and other_condition"], "B1 + 10"),
		(["!negative_condition and other_condition"], "C1 + 15"),
	]


@pytest.mark.django_db
def test_create_deadline_relations_persists_conditional_calculations(
	f_project_subtype,
	f_project_phase_1,
	f_boolean_attribute,
	f_short_string_attribute,
):
	base_deadline = create_deadline(f_project_subtype, f_project_phase_1, "P2")
	target_deadline = create_deadline(f_project_subtype, f_project_phase_1, "E5.3")
	date_type = DateType.objects.create(
		identifier="calculation_days",
		name="Calculation days",
	)
	condition_attribute = f_boolean_attribute
	not_condition_attribute = f_short_string_attribute
	columns, row = relation_row(
		**{
			DEADLINE_ABBREVIATION: target_deadline.abbreviation,
			DEADLINE_CALCULATION_DATE_TYPE: "Calculation days",
			DEADLINE_INITIAL_CALCULATIONS: (
				"{% if bool_attr and !short_string_attr %}P2 + 13{% endif %}"
			),
			DEADLINE_UPDATE_CALCULATIONS: "P2 - 4",
		}
	)
	importer = DeadlineImporter()
	importer._set_row_indexes(columns)

	importer._create_deadline_relations(f_project_subtype, [row])

	initial = target_deadline.initial_calculations.get()
	initial_calculation = initial.datecalculation
	assert initial_calculation.base_date_deadline == base_deadline
	assert initial_calculation.constant == 13
	assert initial_calculation.date_type == date_type
	assert list(initial.conditions.all()) == [condition_attribute]
	assert list(initial.not_conditions.all()) == [not_condition_attribute]
	assert initial.index == 0

	update = target_deadline.update_calculations.get()
	assert update.datecalculation.base_date_deadline == base_deadline
	assert update.datecalculation.constant == -4
	assert update.conditions.count() == 0
	assert update.not_conditions.count() == 0

	assert DateCalculation.objects.count() == 2


@pytest.mark.django_db
def test_create_deadline_relations_supports_attribute_based_calculation_and_ignores_missing_condition(
	f_project_subtype,
	f_project_phase_1,
	f_boolean_attribute,
	f_short_string_attribute,
):
	target_deadline = create_deadline(
		f_project_subtype, f_project_phase_1, "E5.3"
	)
	columns, row = relation_row(
		**{
			DEADLINE_ABBREVIATION: target_deadline.abbreviation,
			DEADLINE_INITIAL_CALCULATIONS: (
				"{% if bool_attr and !missing_attr %}"
				"{{short_string_attr}}"
				"{% endif %}"
			),
		}
	)
	importer = DeadlineImporter()
	importer._set_row_indexes(columns)

	importer._create_deadline_relations(f_project_subtype, [row])

	calculation = target_deadline.initial_calculations.get()
	assert calculation.datecalculation.base_date_attribute == f_short_string_attribute
	assert calculation.datecalculation.base_date_deadline is None
	assert calculation.datecalculation.constant == 0
	assert list(calculation.conditions.all()) == [f_boolean_attribute]
	assert calculation.not_conditions.count() == 0


@pytest.mark.django_db
def test_create_deadline_relations_persists_minimum_distance_direction_and_conditions(
	f_project_subtype,
	f_project_phase_1,
	f_boolean_attribute,
	f_short_string_attribute,
):
	previous_deadline = create_deadline(
		f_project_subtype, f_project_phase_1, "P2"
	)
	current_deadline = create_deadline(
		f_project_subtype, f_project_phase_1, "E5.3"
	)
	condition_attribute = f_boolean_attribute
	not_condition_attribute = f_short_string_attribute
	columns, row = relation_row(
		**{
			DEADLINE_ABBREVIATION: current_deadline.abbreviation,
			DEADLINE_MINIMUM_DISTANCE: (
				"{% if bool_attr and !short_string_attr %}P2 + 13{% endif %}"
				"{% if bool_attr %}P2 - 4{% endif %}"
			),
		}
	)
	importer = DeadlineImporter()
	importer._set_row_indexes(columns)

	importer._create_deadline_relations(f_project_subtype, [row])

	distances = list(DeadlineDistance.objects.order_by("index"))
	assert len(distances) == 2

	forward, reverse = distances
	assert forward.deadline == current_deadline
	assert forward.previous_deadline == previous_deadline
	assert forward.distance_from_previous == 13
	assert forward.index == 0
	assert forward.condition_operator == "and"
	assert {
		(condition.attribute, condition.negate)
		for condition in forward.condition_attributes.all()
	} == {(condition_attribute, False), (not_condition_attribute, True)}

	assert reverse.deadline == previous_deadline
	assert reverse.previous_deadline == current_deadline
	assert reverse.distance_from_previous == 4
	assert reverse.index == 1
	assert reverse.condition_operator is None
	assert list(reverse.condition_attributes.all()) == [
		DeadlineDistanceConditionAttribute.objects.get(
			attribute=condition_attribute,
			negate=False,
		)
	]


@pytest.mark.django_db
def test_create_deadline_relations_supports_unconditional_minimum_distance_rules(
	f_project_subtype,
	f_project_phase_1,
):
	first_previous = create_deadline(f_project_subtype, f_project_phase_1, "P2")
	second_previous = create_deadline(f_project_subtype, f_project_phase_1, "P3")
	current_deadline = create_deadline(
		f_project_subtype, f_project_phase_1, "E5.3"
	)
	columns, row = relation_row(
		**{
			DEADLINE_ABBREVIATION: current_deadline.abbreviation,
			DEADLINE_MINIMUM_DISTANCE: "P2; P3 + 6",
		}
	)
	importer = DeadlineImporter()
	importer._set_row_indexes(columns)

	importer._create_deadline_relations(f_project_subtype, [row])

	distances = list(DeadlineDistance.objects.order_by("index"))
	assert len(distances) == 2
	assert [
		(
			distance.deadline,
			distance.previous_deadline,
			distance.distance_from_previous,
			distance.index,
			distance.condition_operator,
			distance.condition_attributes.count(),
		)
		for distance in distances
	] == [
		(current_deadline, first_previous, 0, 0, None, 0),
		(current_deadline, second_previous, 6, 1, None, 0),
	]


@pytest.mark.django_db
def test_create_deadline_relations_supports_or_and_subtype_distance_conditions(
	f_project_subtype,
	f_project_phase_1,
	f_boolean_attribute,
	f_short_string_attribute,
):
	f_project_subtype.name = "M"
	f_project_subtype.save(update_fields=["name"])
	previous_deadline = create_deadline(
		f_project_subtype, f_project_phase_1, "P2"
	)
	current_deadline = create_deadline(
		f_project_subtype, f_project_phase_1, "E5.3"
	)
	columns, row = relation_row(
		**{
			DEADLINE_ABBREVIATION: current_deadline.abbreviation,
			DEADLINE_MINIMUM_DISTANCE: (
				"{% if bool_attr or short_string_attr %}P2 + 5{% endif %}"
				'{% if kaavaprosessin_kokoluokka in ["M", "S"] %}'
				"P2 + 7{% endif %}"
				'{% if kaavaprosessin_kokoluokka == "XL" %}'
				"P2 + 11{% endif %}"
			),
		}
	)
	importer = DeadlineImporter()
	importer._set_row_indexes(columns)

	importer._create_deadline_relations(f_project_subtype, [row])

	distances = list(DeadlineDistance.objects.order_by("index"))
	assert len(distances) == 2
	or_distance, subtype_distance = distances
	assert or_distance.distance_from_previous == 5
	assert or_distance.condition_operator == "or"
	assert set(or_distance.condition_attributes.all()) == {
		DeadlineDistanceConditionAttribute.objects.get(
			attribute=f_boolean_attribute,
			negate=False,
		),
		DeadlineDistanceConditionAttribute.objects.get(
			attribute=f_short_string_attribute,
			negate=False,
		),
	}
	assert subtype_distance.distance_from_previous == 7
	assert subtype_distance.deadline == current_deadline
	assert subtype_distance.previous_deadline == previous_deadline
	assert subtype_distance.condition_operator is None
	assert subtype_distance.condition_attributes.count() == 0


@pytest.mark.django_db
def test_create_deadlines_persists_resolved_relations_and_deadline_types(
	f_project_subtype,
	f_project_phase_1,
	f_short_string_attribute,
	f_boolean_attribute,
):
	date_type = DateType.objects.create(
		identifier="deadline_days",
		name="Deadline days",
	)
	columns, row = deadline_row(
		**{
			DEADLINE_ATTRIBUTE_IDENTIFIER: f_short_string_attribute.identifier,
			DEADLINE_CONFIRMATION_ATTRIBUTE_IDENTIFIER: f_boolean_attribute.identifier,
			DEADLINE_ABBREVIATION: "P2",
			DEADLINE_TYPE: "vaiheen alkupiste; vaiheen päätepiste; tuntematon tyyppi",
			DEADLINE_DATE_TYPE: "Deadline days",
			DEADLINE_PHASE: "Käynnistys",
			DEADLINE_ERROR_PAST_DUE: "Past due error",
			DEADLINE_ERROR_DATE_TYPE_MISMATCH: "Mismatch error",
			DEADLINE_ERROR_MIN_DISTANCE_PREV: "Min distance error",
			DEADLINE_WARNING_MIN_DISTANCE_NEXT: "Next warning",
			DEADLINE_GROUP: "Group A",
		}
	)
	importer = DeadlineImporter()
	importer._set_row_indexes(columns)

	importer._create_deadlines(f_project_subtype, [row])

	deadline = Deadline.objects.get(subtype=f_project_subtype, abbreviation="P2")
	assert deadline.attribute == f_short_string_attribute
	assert deadline.confirmation_attribute == f_boolean_attribute
	assert deadline.deadline_types == [
		Deadline.TYPE_PHASE_START,
		Deadline.TYPE_PHASE_END,
	]
	assert deadline.date_type == date_type
	assert deadline.phase == f_project_phase_1
	assert deadline.error_past_due == "Past due error"
	assert deadline.error_date_type_mismatch == "Mismatch error"
	assert deadline.error_min_distance_previous == "Min distance error"
	assert deadline.warning_min_distance_next == "Next warning"
	assert deadline.deadlinegroup == "Group A"
	assert deadline.default_to_created_at is False
	assert deadline.index == 1
	assert list(deadline.condition_attributes.all()) == []


@pytest.mark.django_db
def test_create_deadlines_sets_default_to_created_at_for_project_start_attribute(
	f_project_subtype,
	f_project_phase_1,
):
	start_attribute = Attribute.objects.create(
		name="Start date",
		identifier=DEADLINE_CREATED_AT_ATTRIBUTE_FIELD_VALUE,
		value_type=Attribute.TYPE_DATE,
	)
	columns, row = deadline_row(
		**{
			DEADLINE_ATTRIBUTE_IDENTIFIER: start_attribute.identifier,
			DEADLINE_ABBREVIATION: "P1",
			DEADLINE_PHASE: "Käynnistys",
		}
	)
	importer = DeadlineImporter()
	importer._set_row_indexes(columns)

	importer._create_deadlines(f_project_subtype, [row])

	deadline = Deadline.objects.get(subtype=f_project_subtype, abbreviation="P1")
	assert deadline.attribute == start_attribute
	assert deadline.default_to_created_at is True


@pytest.mark.django_db
def test_create_deadlines_nulls_invalid_attribute_and_confirmation_attribute(
	f_project_subtype,
	f_project_phase_1,
):
	columns, row = deadline_row(
		**{
			DEADLINE_ATTRIBUTE_IDENTIFIER: "does_not_exist",
			DEADLINE_CONFIRMATION_ATTRIBUTE_IDENTIFIER: "also_missing",
			DEADLINE_ABBREVIATION: "P3",
			DEADLINE_PHASE: "Käynnistys",
		}
	)
	importer = DeadlineImporter()
	importer._set_row_indexes(columns)

	importer._create_deadlines(f_project_subtype, [row])

	deadline = Deadline.objects.get(subtype=f_project_subtype, abbreviation="P3")
	assert deadline.attribute is None
	assert deadline.confirmation_attribute is None
	assert deadline.default_to_created_at is False


@pytest.mark.django_db
def test_create_deadlines_skips_row_with_unmatched_phase(
	f_project_subtype,
	f_project_phase_1,
):
	columns, row = deadline_row(
		**{
			DEADLINE_ABBREVIATION: "P4",
			DEADLINE_PHASE: "Vaihe jota ei ole",
		}
	)
	importer = DeadlineImporter()
	importer._set_row_indexes(columns)

	importer._create_deadlines(f_project_subtype, [row])

	assert not Deadline.objects.filter(
		subtype=f_project_subtype, abbreviation="P4"
	).exists()


@pytest.mark.django_db
def test_create_deadlines_attaches_condition_attribute_from_simple_if_tag(
	f_project_subtype,
	f_project_phase_1,
	f_boolean_attribute,
):
	columns, row = deadline_row(
		**{
			DEADLINE_ABBREVIATION: "P5",
			DEADLINE_PHASE: "Käynnistys",
			DEADLINE_ATTRIBUTE_CONDITION: "{% if bool_attr %}",
		}
	)
	importer = DeadlineImporter()
	importer._set_row_indexes(columns)

	importer._create_deadlines(f_project_subtype, [row])

	deadline = Deadline.objects.get(subtype=f_project_subtype, abbreviation="P5")
	assert list(deadline.condition_attributes.all()) == [f_boolean_attribute]


@pytest.mark.django_db
def test_create_deadlines_skips_row_for_non_matching_subtype_condition(
	f_project_subtype,
	f_project_phase_1,
):
	f_project_subtype.name = "M"
	f_project_subtype.save(update_fields=["name"])
	columns, row = deadline_row(
		**{
			DEADLINE_ABBREVIATION: "P6",
			DEADLINE_PHASE: "Käynnistys",
			DEADLINE_ATTRIBUTE_CONDITION: 'kaavaprosessin_kokoluokka == "XL"',
		}
	)
	importer = DeadlineImporter()
	importer._set_row_indexes(columns)

	importer._create_deadlines(f_project_subtype, [row])

	assert not Deadline.objects.filter(
		subtype=f_project_subtype, abbreviation="P6"
	).exists()


@pytest.mark.django_db
def test_create_deadlines_skips_semicolon_condition_for_non_matching_subtype(
	f_project_subtype,
	f_project_phase_1,
):
	f_project_subtype.name = "M"
	f_project_subtype.save(update_fields=["name"])
	columns, row = deadline_row(
		**{
			DEADLINE_ABBREVIATION: "P7",
			DEADLINE_PHASE: "Käynnistys",
			DEADLINE_ATTRIBUTE_CONDITION: (
				'kaavaprosessin_kokoluokka == "XL"; {% if bool_attr %}'
			),
		}
	)
	importer = DeadlineImporter()
	importer._set_row_indexes(columns)

	importer._create_deadlines(f_project_subtype, [row])

	assert not Deadline.objects.filter(
		subtype=f_project_subtype, abbreviation="P7"
	).exists()


@pytest.mark.django_db
def test_create_deadline_relations_skips_semicolon_condition_for_non_matching_subtype(
	f_project_subtype,
	f_project_phase_1,
):
	f_project_subtype.name = "M"
	f_project_subtype.save(update_fields=["name"])
	target_deadline = create_deadline(
		f_project_subtype, f_project_phase_1, "E5.3"
	)
	create_deadline(f_project_subtype, f_project_phase_1, "P2")
	columns, row = relation_row(
		**{
			DEADLINE_ABBREVIATION: target_deadline.abbreviation,
			DEADLINE_ATTRIBUTE_CONDITION: (
				'kaavaprosessin_kokoluokka == "XL"; {% if bool_attr %}'
			),
			DEADLINE_INITIAL_CALCULATIONS: "P2 + 1",
		}
	)
	importer = DeadlineImporter()
	importer._set_row_indexes(columns)

	importer._create_deadline_relations(f_project_subtype, [row])

	assert target_deadline.initial_calculations.count() == 0
	assert DateCalculation.objects.count() == 0
