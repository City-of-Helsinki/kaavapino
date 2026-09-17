from types import SimpleNamespace

import pytest

from projects.models import CommonProjectPhase, Deadline, ProjectPhase, ProjectSubtype
from projects.models.utils import truncate_identifier
from projects.serializers.utils import (
    _is_attribute_required,
    _set_fieldset_path,
    should_display_deadline,
)


def _fieldset_path(parent_identifier, index):
    # Mirrors the shape produced by ProjectAttributeFile.fieldset_path
    return [{"parent": SimpleNamespace(identifier=parent_identifier), "index": index}]


def _make_phase(subtype, name, index=0):
    common_phase = CommonProjectPhase.objects.create(
        name=name,
        color="color--tram",
        color_code="#009246",
    )
    return ProjectPhase.objects.create(
        common_project_phase=common_phase,
        project_subtype=subtype,
        index=index,
    )


def _make_deadline(subtype, phase, deadlinegroup=None):
    return Deadline.objects.create(
        abbreviation="dl",
        phase=phase,
        subtype=subtype,
        deadlinegroup=deadlinegroup,
    )


@pytest.mark.django_db
def test_is_attribute_required(f_short_string_attribute):
    required = _is_attribute_required(f_short_string_attribute)
    assert required is False

    # required = True
    f_short_string_attribute.required = True
    required = _is_attribute_required(f_short_string_attribute)
    assert required is True

    # required = True, generated = True
    f_short_string_attribute.generated = True
    required = _is_attribute_required(f_short_string_attribute)
    assert required is False


def test_identifier_truncation():
    identifier = "identifier"

    # Length is the same, nothing is done
    truncated_identifier = truncate_identifier(identifier, length=len(identifier))
    assert truncated_identifier == identifier

    # Length is bigger, not thing is done
    truncated_identifier = truncate_identifier(identifier, length=len(identifier) + 5)
    assert truncated_identifier == identifier

    # Length is smaller, identifier is truncated
    truncated_identifier = truncate_identifier(identifier, length=len(identifier) - 1)
    assert identifier != truncated_identifier
    assert identifier[:-5] == truncated_identifier[:-4]
    assert len(truncated_identifier) == len(identifier) - 1

    # Check that truncation produces the currently expected result (sha1)
    assert truncated_identifier == "identfae9"

    # Truncating consistently returns the same result
    t1 = truncate_identifier(identifier, length=len(identifier) - 1)
    t2 = truncate_identifier(identifier, length=len(identifier) - 1)

    assert t1 == t2


@pytest.mark.django_db
def test_should_display_deadline_true_when_project_missing(f_project_subtype, f_project_phase_1):
    """Bug: filtering code passing project=None must not hide every deadline."""
    deadline = _make_deadline(f_project_subtype, f_project_phase_1)

    assert should_display_deadline(None, deadline) is True


@pytest.mark.django_db
def test_should_display_deadline_true_when_deadline_missing(f_project):
    """Bug: a falsy/None deadline must not be treated as "hidden"."""
    assert should_display_deadline(f_project, None) is True


@pytest.mark.django_db
def test_should_display_deadline_false_for_subtype_mismatch(f_project, f_project_type, f_project_phase_1):
    """Bug: a deadline belonging to another project subtype must never be shown."""
    other_subtype = ProjectSubtype.objects.create(
        name="other", project_type=f_project_type, index=1
    )
    deadline = _make_deadline(other_subtype, f_project_phase_1)

    assert should_display_deadline(f_project, deadline) is False


@pytest.mark.django_db
def test_should_display_deadline_false_when_principles_phase_not_enabled(f_project, f_project_subtype):
    """Bug: "Periaatteet" deadlines must be hidden unless create_principles is set."""
    f_project.create_principles = False
    phase = _make_phase(f_project_subtype, "Periaatteet")
    deadline = _make_deadline(f_project_subtype, phase)

    assert should_display_deadline(f_project, deadline) is False


@pytest.mark.django_db
def test_should_display_deadline_true_when_principles_phase_enabled(f_project, f_project_subtype):
    """Bug: enabling create_principles must not still hide "Periaatteet" deadlines."""
    f_project.create_principles = True
    phase = _make_phase(f_project_subtype, "Periaatteet")
    deadline = _make_deadline(f_project_subtype, phase)

    assert should_display_deadline(f_project, deadline) is True


@pytest.mark.django_db
def test_should_display_deadline_false_when_draft_phase_not_enabled(f_project, f_project_subtype):
    """Bug: "Luonnos" deadlines must be hidden unless create_draft is set."""
    f_project.create_draft = False
    phase = _make_phase(f_project_subtype, "Luonnos")
    deadline = _make_deadline(f_project_subtype, phase)

    assert should_display_deadline(f_project, deadline) is False


@pytest.mark.django_db
def test_should_display_deadline_true_when_draft_phase_enabled(f_project, f_project_subtype):
    """Bug: enabling create_draft must not still hide "Luonnos" deadlines."""
    f_project.create_draft = True
    phase = _make_phase(f_project_subtype, "Luonnos")
    deadline = _make_deadline(f_project_subtype, phase)

    assert should_display_deadline(f_project, deadline) is True


@pytest.mark.django_db
def test_should_display_deadline_true_when_no_deadlinegroup(f_project, f_project_subtype, f_project_phase_1):
    """Bug: deadlines without a deadlinegroup must default to visible."""
    deadline = _make_deadline(f_project_subtype, f_project_phase_1, deadlinegroup=None)

    assert should_display_deadline(f_project, deadline) is True


@pytest.mark.django_db
def test_should_display_deadline_true_when_vis_bool_missing_for_first_slot(
    f_project, f_project_subtype, f_project_phase_1
):
    """Bug: missing vis_bool attribute data for the default (slot "_1") deadline must not hide it."""
    f_project.attribute_data = {}
    deadline = _make_deadline(
        f_project_subtype, f_project_phase_1, deadlinegroup="oas_esillaolokerta_1"
    )

    assert should_display_deadline(f_project, deadline) is True


@pytest.mark.django_db
def test_should_display_deadline_false_when_vis_bool_missing_for_non_first_slot(
    f_project, f_project_subtype, f_project_phase_1
):
    """Bug: unlike slot "_1", missing vis_bool data for slot "_2" must not default to visible."""
    f_project.attribute_data = {}
    deadline = _make_deadline(
        f_project_subtype, f_project_phase_1, deadlinegroup="oas_esillaolokerta_2"
    )

    assert should_display_deadline(f_project, deadline) is False


@pytest.mark.django_db
def test_should_display_deadline_true_when_vis_bool_set_true(
    f_project, f_project_subtype, f_project_phase_1
):
    """Bug: an explicit True vis_bool must show the deadline, regardless of slot."""
    f_project.attribute_data = {"jarjestetaan_oas_esillaolo_2": True}
    deadline = _make_deadline(
        f_project_subtype, f_project_phase_1, deadlinegroup="oas_esillaolokerta_2"
    )

    assert should_display_deadline(f_project, deadline) is True


@pytest.mark.django_db
def test_should_display_deadline_false_when_vis_bool_set_false(
    f_project, f_project_subtype, f_project_phase_1
):
    """Bug: an explicit False vis_bool must hide the deadline, even for the default slot "_1"."""
    f_project.attribute_data = {"jarjestetaan_oas_esillaolo_1": False}
    deadline = _make_deadline(
        f_project_subtype, f_project_phase_1, deadlinegroup="oas_esillaolokerta_1"
    )

    assert should_display_deadline(f_project, deadline) is False


def test_set_fieldset_path_creates_missing_parent_key_padded_to_index():
    """Bug: a brand new fieldset key must pad earlier indices instead of just appending."""
    parent_obj = {}

    _set_fieldset_path({}, _fieldset_path("photos", 2), parent_obj, 0, "caption", "hello")

    assert parent_obj == {"photos": [None, None, {"caption": "hello"}]}


def test_set_fieldset_path_merges_fieldset_content_for_missing_key():
    """Bug: sibling fields from fieldset_content must not be dropped when creating a new entry."""
    parent_obj = {}

    _set_fieldset_path(
        {"extra": "v0"}, _fieldset_path("photos", 0), parent_obj, 0, "caption", "hello"
    )

    assert parent_obj == {"photos": [{"extra": "v0", "caption": "hello"}]}


def test_set_fieldset_path_merges_fieldset_content_for_short_existing_list():
    """Bug: extending a too-short list (IndexError path) must merge fieldset_content the same as a new key."""
    parent_obj = {"photos": []}

    _set_fieldset_path(
        {"extra": "v0"}, _fieldset_path("photos", 0), parent_obj, 0, "caption", "hello"
    )

    assert parent_obj == {"photos": [{"extra": "v0", "caption": "hello"}]}


def test_set_fieldset_path_preserves_existing_keys_on_existing_entry():
    """Bug: setting a new field on an existing fieldset entry must not clobber its other fields."""
    parent_obj = {"photos": [{"other": "kept"}]}

    _set_fieldset_path({}, _fieldset_path("photos", 0), parent_obj, 0, "caption", "hello")

    assert parent_obj == {"photos": [{"other": "kept", "caption": "hello"}]}


def test_set_fieldset_path_fieldset_content_overwrites_existing_keys():
    """Bug: fieldset_content values must take precedence over the existing entry's values."""
    parent_obj = {"photos": [{"other": "kept"}]}

    _set_fieldset_path(
        {"other": "newval", "added": "x"},
        _fieldset_path("photos", 0),
        parent_obj,
        0,
        "caption",
        "hello",
    )

    assert parent_obj == {
        "photos": [{"other": "newval", "added": "x", "caption": "hello"}]
    }


def test_set_fieldset_path_pads_multiple_missing_indices():
    """Bug: jumping several indices ahead must not miscount how many None placeholders to insert."""
    parent_obj = {"photos": [{"a": 1}]}

    _set_fieldset_path({}, _fieldset_path("photos", 3), parent_obj, 0, "caption", "hello")

    assert parent_obj == {"photos": [{"a": 1}, None, None, {"caption": "hello"}]}


def test_set_fieldset_path_raises_on_none_fieldset_content_for_existing_entry():
    """Bug: passing None (instead of {}) as fieldset_content crashes when merging into an existing entry."""
    parent_obj = {"photos": [{"other": "kept"}]}
    path = _fieldset_path("photos", 0)

    with pytest.raises(AttributeError, match="'NoneType' object has no attribute 'items'"):
        _set_fieldset_path(None, path, parent_obj, 0, "caption", "hello")
