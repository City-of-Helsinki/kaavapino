from projects.importing.deadline import DeadlineImporter


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
