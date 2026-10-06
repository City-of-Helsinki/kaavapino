import pytest

from projects.importing.deadline import (
	DEADLINE_ABBREVIATION,
	DEADLINE_ATTRIBUTE_CONDITION,
	DEADLINE_CALCULATION_DATE_TYPE,
	DEADLINE_INITIAL_CALCULATIONS,
	DEADLINE_MINIMUM_DISTANCE,
	DEADLINE_UPDATE_CALCULATIONS,
	DeadlineImporter,
)
from projects.models import (
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
	assert [
		(condition.attribute, condition.negate)
		for condition in forward.condition_attributes.all()
	] == [(condition_attribute, False), (not_condition_attribute, True)]

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
