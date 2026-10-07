import datetime
import logging

import pytest
from rest_framework.exceptions import ValidationError

from projects.models import (
    Attribute,
    CommonProjectPhase,
    Deadline,
    ProjectDeadline,
    ProjectPhase,
    ProjectPhaseSection,
    ProjectPhaseSectionAttribute,
)
from projects.serializers.project import ProjectSerializer


class _FakeRequest:
    """Minimal stand-in for a DRF Request, exposing only what the serializer reads."""

    def __init__(self, data, user):
        self.data = data
        self.user = user
        self.GET = {}
        self.query_params = {}


def _make_serializer(
    project, attribute_data, extra_context=None, validate=None, request_user=None,
):
    data = {"attribute_data": attribute_data}
    if validate is not None:
        data["validate_attribute_data"] = validate
    request = _FakeRequest(data=data, user=request_user or project.user)
    context = {"request": request, **(extra_context or {})}
    return ProjectSerializer(instance=project, context=context)


def _attach_attribute_to_phase(project, attribute, index):
    common_phase = CommonProjectPhase.objects.create(name=f"Phase {index}")
    phase = ProjectPhase.objects.create(
        common_project_phase=common_phase,
        project_subtype=project.subtype,
        index=index,
    )
    section = ProjectPhaseSection.objects.create(
        phase=phase,
        name=f"Section {index}",
    )
    ProjectPhaseSectionAttribute.objects.create(
        attribute=attribute,
        section=section,
    )
    return phase


@pytest.mark.django_db
def test_returns_only_static_properties_when_attribute_data_is_empty(f_project):
    name_attribute = Attribute.objects.create(
        name="Project name",
        identifier="project_name_field",
        value_type=Attribute.TYPE_SHORT_STRING,
        static_property="name",
    )
    serializer = _make_serializer(f_project, attribute_data={})

    result = serializer._validate_attribute_data(
        {}, {"name": "New Name"}, f_project.user, False,
    )

    assert result == {name_attribute.identifier: "New Name"}


@pytest.mark.django_db
def test_accepts_valid_value_for_existing_section_attribute(
    f_project, f_project_section_attribute_1
):
    attribute_data = {"short_string_attr": "hello"}
    serializer = _make_serializer(f_project, attribute_data)

    result = serializer._validate_attribute_data(
        attribute_data, {}, f_project.user, False,
    )

    assert result == {"short_string_attr": "hello"}


@pytest.mark.django_db
def test_drops_attribute_from_locked_past_phase(
    f_project, f_long_string_attribute
):
    _attach_attribute_to_phase(f_project, f_long_string_attribute, index=2)
    f_project.phase = _attach_attribute_to_phase(
        f_project, Attribute.objects.create(
            name="Current phase field",
            identifier="current_phase_field",
            value_type=Attribute.TYPE_SHORT_STRING,
        ),
        index=4,
    )
    f_project.save()
    identifier = f_long_string_attribute.identifier
    attribute_data = {identifier: "attempted edit"}
    serializer = _make_serializer(f_project, attribute_data)

    result = serializer._validate_attribute_data(
        attribute_data, {}, f_project.user, False,
    )

    assert identifier not in result


@pytest.mark.django_db
@pytest.mark.parametrize("field_phase_index", [4, 5])
def test_accepts_current_and_upcoming_phase_attributes(
    f_project, f_long_string_attribute, field_phase_index
):
    f_project.phase = _attach_attribute_to_phase(
        f_project, f_long_string_attribute, index=4,
    )
    f_project.save()
    if field_phase_index != 4:
        _attach_attribute_to_phase(
            f_project, f_long_string_attribute, index=field_phase_index,
        )
    identifier = f_long_string_attribute.identifier
    attribute_data = {identifier: "allowed edit"}
    serializer = _make_serializer(f_project, attribute_data)

    result = serializer._validate_attribute_data(
        attribute_data, {}, f_project.user, False,
    )

    assert result[identifier] == "allowed edit"


@pytest.mark.django_db
def test_owner_edit_override_allows_locked_past_phase_field(
    f_project, f_long_string_attribute
):
    _attach_attribute_to_phase(f_project, f_long_string_attribute, index=2)
    f_project.phase = _attach_attribute_to_phase(
        f_project,
        Attribute.objects.create(
            name="Current phase field",
            identifier="current_phase_field",
            value_type=Attribute.TYPE_SHORT_STRING,
        ),
        index=4,
    )
    f_project.owner_edit_override = True
    f_project.save()
    identifier = f_long_string_attribute.identifier
    attribute_data = {identifier: "owner edit"}
    serializer = _make_serializer(f_project, attribute_data)

    result = serializer._validate_attribute_data(
        attribute_data, {}, f_project.user, owner_edit_override=True,
    )

    assert result[identifier] == "owner edit"


@pytest.mark.django_db
def test_owner_edit_override_does_not_allow_other_users_to_edit_past_phase(
    f_project, f_long_string_attribute, f_user2
):
    _attach_attribute_to_phase(f_project, f_long_string_attribute, index=2)
    f_project.phase = _attach_attribute_to_phase(
        f_project,
        Attribute.objects.create(
            name="Current phase field",
            identifier="current_phase_field",
            value_type=Attribute.TYPE_SHORT_STRING,
        ),
        index=4,
    )
    f_project.owner_edit_override = True
    f_project.save()
    identifier = f_long_string_attribute.identifier
    attribute_data = {identifier: "unauthorized edit"}
    serializer = _make_serializer(
        f_project, attribute_data, request_user=f_user2,
    )

    result = serializer._validate_attribute_data(
        attribute_data, {}, f_project.user, owner_edit_override=True,
    )

    assert identifier not in result


@pytest.mark.django_db
def test_unknown_identifier_is_dropped_without_raising(
    f_project, f_project_section_attribute_1, caplog
):
    attribute_data = {"does_not_exist": "value"}
    serializer = _make_serializer(f_project, attribute_data)

    with caplog.at_level(logging.WARNING):
        result = serializer._validate_attribute_data(
            attribute_data, {}, f_project.user, False,
        )

    assert result == {}
    assert "does_not_exist" in caplog.text


@pytest.mark.django_db
def test_raises_validation_error_for_invalid_choice_value(
    f_project, f_choice_attribute, f_project_section_1,
    project_phase_section_attribute_factory,
):
    project_phase_section_attribute_factory(
        attribute=f_choice_attribute, section=f_project_section_1,
    )
    attribute_data = {"choice_attr": "not_a_real_choice"}
    serializer = _make_serializer(f_project, attribute_data)

    with pytest.raises(ValidationError):
        serializer._validate_attribute_data(
            attribute_data, {}, f_project.user, False,
        )


@pytest.mark.django_db
def test_skips_validation_when_validate_attribute_data_is_false(
    f_project, f_choice_attribute, f_project_section_1,
    project_phase_section_attribute_factory,
):
    project_phase_section_attribute_factory(
        attribute=f_choice_attribute, section=f_project_section_1,
    )
    attribute_data = {"choice_attr": "not_a_real_choice"}
    serializer = _make_serializer(f_project, attribute_data, validate=False)

    # Invalid value would normally raise; disabling validation must suppress that
    result = serializer._validate_attribute_data(
        attribute_data, {}, f_project.user, False,
    )

    assert "choice_attr" not in result


@pytest.mark.django_db
def test_multiple_choice_none_value_resets_to_empty_list(
    f_project, f_multi_choice_attribute, f_project_section_1,
    project_phase_section_attribute_factory,
):
    project_phase_section_attribute_factory(
        attribute=f_multi_choice_attribute, section=f_project_section_1,
    )
    attribute_data = {"multi_choice_attr": None}
    serializer = _make_serializer(f_project, attribute_data)

    result = serializer._validate_attribute_data(
        attribute_data, {}, f_project.user, False,
    )

    assert result["multi_choice_attr"] == []


@pytest.mark.django_db
def test_confirmed_deadline_attribute_cannot_be_edited(
    f_project, f_project_section_attribute_1, f_boolean_attribute,
    f_project_phase_1, f_project_subtype,
):
    deadline = Deadline.objects.create(
        abbreviation="T1",
        phase=f_project_phase_1,
        subtype=f_project_subtype,
        attribute=f_project_section_attribute_1.attribute,
        confirmation_attribute=f_boolean_attribute,
    )
    # Previously confirmed: confirmation attribute already truthy in stored data
    f_project.attribute_data = {f_boolean_attribute.identifier: True}
    f_project.save()

    project_deadline = ProjectDeadline.objects.create(
        deadline=deadline,
        project=f_project,
        date=datetime.date(2026, 1, 1),
        editable=True,
    )
    f_project.deadlines.set([project_deadline])

    identifier = f_project_section_attribute_1.attribute.identifier
    attribute_data = {identifier: "attempted new value"}
    serializer = _make_serializer(
        f_project, attribute_data, extra_context={"confirmed_fields": []},
    )
    # Mock out the expensive cascade engine; only the confirmed-deadline
    # exclusion logic in _validate_attribute_data is under test here.
    f_project.get_preview_deadlines = lambda *args, **kwargs: {}

    result = serializer._validate_attribute_data(
        attribute_data, {}, f_project.user, False,
    )

    assert identifier not in result
