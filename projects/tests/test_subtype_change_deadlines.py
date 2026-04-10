import datetime

import pytest
from django.db.models.signals import pre_save

from projects.models import (
    Attribute,
    CommonProjectPhase,
    DateCalculation,
    Deadline,
    DeadlineDateCalculation,
    ProjectDeadline,
    ProjectPhase,
    ProjectSubtype,
    ProjectType,
)
from projects.signals.handlers import save_attribute_data_subtype
from projects.tests.factories import ProjectFactory


def _date(value):
    return datetime.date.fromisoformat(value)


def _create_phase(subtype, name, index):
    common_phase = CommonProjectPhase.objects.create(name=name, index=index)
    return ProjectPhase.objects.create(
        common_project_phase=common_phase,
        project_subtype=subtype,
        index=index,
    )


def _create_date_attribute(identifier):
    return Attribute.objects.create(
        identifier=identifier,
        name=identifier,
        value_type=Attribute.TYPE_DATE,
    )


def _create_bool_attribute(identifier):
    return Attribute.objects.create(
        identifier=identifier,
        name=identifier,
        value_type=Attribute.TYPE_BOOLEAN,
    )


def _create_deadline(subtype, phase, abbreviation, index, attribute=None, confirmation_attribute=None):
    return Deadline.objects.create(
        abbreviation=abbreviation,
        subtype=subtype,
        phase=phase,
        index=index,
        attribute=attribute,
        confirmation_attribute=confirmation_attribute,
    )


def _attach_initial_calculation(deadline, base_deadline, constant):
    date_calculation = DateCalculation.objects.create(
        base_date_deadline=base_deadline,
        constant=constant,
    )
    deadline_calculation = DeadlineDateCalculation.objects.create(
        deadline=deadline,
        datecalculation=date_calculation,
    )
    deadline.initial_calculations.add(deadline_calculation)


def _attach_update_calculation(deadline, base_deadline, constant):
    date_calculation = DateCalculation.objects.create(
        base_date_deadline=base_deadline,
        constant=constant,
    )
    deadline_calculation = DeadlineDateCalculation.objects.create(
        deadline=deadline,
        datecalculation=date_calculation,
    )
    deadline.update_calculations.add(deadline_calculation)


@pytest.fixture
def disconnect_signals():
    pre_save.disconnect(save_attribute_data_subtype, sender=ProjectFactory._meta.model)
    yield
    pre_save.connect(save_attribute_data_subtype, sender=ProjectFactory._meta.model)


@pytest.fixture
def project_type():
    project_type, _ = ProjectType.objects.get_or_create(name="asemakaava")
    return project_type


@pytest.mark.django_db
def test_subtype_change_copies_old_dates_generates_new_current_dates_and_keeps_confirmed_deadlines_fixed(
    disconnect_signals,
    project_type,
):
    """
    Regression coverage for subtype change deadline migration.

    Catches four failure modes at once:
    - copied deadlines lose their old value when subtype swaps deadline objects
    - completely new deadlines are created without initial_calculations
    - forward update_calculations do not run from the first new current-phase deadline
    - confirmed deadlines move even though their confirmation flag is already true
    """
    old_subtype = ProjectSubtype.objects.create(
        project_type=project_type,
        name="Subtype old",
        index=1,
    )
    new_subtype = ProjectSubtype.objects.create(
        project_type=project_type,
        name="Subtype new",
        index=2,
    )

    old_past_phase = _create_phase(old_subtype, "Past", 1)
    old_current_phase = _create_phase(old_subtype, "Current", 2)
    old_future_phase = _create_phase(old_subtype, "Future", 3)
    new_past_phase = _create_phase(new_subtype, "Past", 1)
    new_current_phase = _create_phase(new_subtype, "Current", 2)
    new_future_phase = _create_phase(new_subtype, "Future", 3)

    past_attr = _create_date_attribute("subtype_change_past")
    new_current_attr = _create_date_attribute("subtype_change_new_current")
    future_attr = _create_date_attribute("subtype_change_future")
    confirmed_attr = _create_date_attribute("subtype_change_confirmed")
    after_attr = _create_date_attribute("subtype_change_after")
    confirmation_flag_attr = _create_bool_attribute("subtype_change_confirmed_flag")

    old_past = _create_deadline(old_subtype, old_past_phase, "OLD_PAST", 10, attribute=past_attr)
    old_future = _create_deadline(old_subtype, old_current_phase, "OLD_FUTURE", 20, attribute=future_attr)
    old_confirmed = _create_deadline(
        old_subtype,
        old_current_phase,
        "OLD_CONFIRMED",
        30,
        attribute=confirmed_attr,
        confirmation_attribute=confirmation_flag_attr,
    )
    old_after = _create_deadline(old_subtype, old_future_phase, "OLD_AFTER", 40, attribute=after_attr)

    new_past = _create_deadline(new_subtype, new_past_phase, "NEW_PAST", 10, attribute=past_attr)
    new_current = _create_deadline(new_subtype, new_current_phase, "NEW_CURRENT", 20, attribute=new_current_attr)
    new_future = _create_deadline(new_subtype, new_current_phase, "NEW_FUTURE", 30, attribute=future_attr)
    new_confirmed = _create_deadline(
        new_subtype,
        new_current_phase,
        "NEW_CONFIRMED",
        40,
        attribute=confirmed_attr,
        confirmation_attribute=confirmation_flag_attr,
    )
    new_after = _create_deadline(new_subtype, new_future_phase, "NEW_AFTER", 50, attribute=after_attr)

    _attach_initial_calculation(new_current, new_past, 5)
    _attach_update_calculation(new_future, new_current, 4)
    _attach_update_calculation(new_confirmed, new_future, 4)
    _attach_update_calculation(new_after, new_confirmed, 3)

    project = ProjectFactory.create(
        subtype=old_subtype,
        phase=old_current_phase,
        attribute_data={
            past_attr.identifier: "2026-01-01",
            future_attr.identifier: "2026-01-07",
            confirmed_attr.identifier: "2026-01-09",
            after_attr.identifier: "2026-01-10",
            confirmation_flag_attr.identifier: True,
        },
    )

    old_project_deadlines = [
        ProjectDeadline.objects.create(project=project, deadline=old_past, date=_date("2026-01-01")),
        ProjectDeadline.objects.create(project=project, deadline=old_future, date=_date("2026-01-07")),
        ProjectDeadline.objects.create(project=project, deadline=old_confirmed, date=_date("2026-01-09")),
        ProjectDeadline.objects.create(project=project, deadline=old_after, date=_date("2026-01-10")),
    ]
    project.deadlines.set(old_project_deadlines)

    project.subtype = new_subtype
    project.update_deadlines_on_subtype_change()
    project.refresh_from_db()

    assert not ProjectDeadline.objects.filter(project=project, deadline__subtype=old_subtype).exists()

    assert project.deadlines.get(deadline=new_past).date == _date("2026-01-01")
    assert project.deadlines.get(deadline=new_current).date == _date("2026-01-06")
    assert project.deadlines.get(deadline=new_future).date == _date("2026-01-10")
    assert project.deadlines.get(deadline=new_confirmed).date == _date("2026-01-09")
    assert project.deadlines.get(deadline=new_after).date == _date("2026-01-12")

    assert project._coerce_date_value(project.attribute_data[past_attr.identifier]) == _date("2026-01-01")
    assert project._coerce_date_value(project.attribute_data[new_current_attr.identifier]) == _date("2026-01-06")
    assert project._coerce_date_value(project.attribute_data[future_attr.identifier]) == _date("2026-01-10")
    assert project._coerce_date_value(project.attribute_data[confirmed_attr.identifier]) == _date("2026-01-09")
    assert project._coerce_date_value(project.attribute_data[after_attr.identifier]) == _date("2026-01-12")


@pytest.mark.django_db
def test_subtype_change_does_not_push_current_phase_deadlines_when_only_new_deadline_is_in_past_phase(
    disconnect_signals,
    project_type,
):
    """
    Regression for phase boundary handling during subtype change.

    A new deadline in a past phase should still get its initial date, but it must not
    trigger update_calculations for the current phase and beyond.
    """
    old_subtype = ProjectSubtype.objects.create(
        project_type=project_type,
        name="Subtype old past-only",
        index=3,
    )
    new_subtype = ProjectSubtype.objects.create(
        project_type=project_type,
        name="Subtype new past-only",
        index=4,
    )

    old_past_phase = _create_phase(old_subtype, "Past 2", 1)
    old_current_phase = _create_phase(old_subtype, "Current 2", 2)
    new_past_phase = _create_phase(new_subtype, "Past 2", 1)
    new_current_phase = _create_phase(new_subtype, "Current 2", 2)

    base_attr = _create_date_attribute("subtype_change_base_past")
    new_past_attr = _create_date_attribute("subtype_change_added_past")
    future_attr = _create_date_attribute("subtype_change_current_future")

    old_base = _create_deadline(old_subtype, old_past_phase, "OLD_BASE", 10, attribute=base_attr)
    old_future = _create_deadline(old_subtype, old_current_phase, "OLD_CURRENT", 20, attribute=future_attr)

    new_base = _create_deadline(new_subtype, new_past_phase, "NEW_BASE", 10, attribute=base_attr)
    new_added_past = _create_deadline(new_subtype, new_past_phase, "NEW_ADDED_PAST", 20, attribute=new_past_attr)
    new_future = _create_deadline(new_subtype, new_current_phase, "NEW_CURRENT", 30, attribute=future_attr)

    _attach_initial_calculation(new_added_past, new_base, 2)
    _attach_update_calculation(new_future, new_added_past, 10)

    project = ProjectFactory.create(
        subtype=old_subtype,
        phase=old_current_phase,
        attribute_data={
            base_attr.identifier: "2026-02-01",
            future_attr.identifier: "2026-02-05",
        },
    )

    old_project_deadlines = [
        ProjectDeadline.objects.create(project=project, deadline=old_base, date=_date("2026-02-01")),
        ProjectDeadline.objects.create(project=project, deadline=old_future, date=_date("2026-02-05")),
    ]
    project.deadlines.set(old_project_deadlines)

    project.subtype = new_subtype
    project.update_deadlines_on_subtype_change()
    project.refresh_from_db()

    assert project.deadlines.get(deadline=new_base).date == _date("2026-02-01")
    assert project.deadlines.get(deadline=new_added_past).date == _date("2026-02-03")
    assert project.deadlines.get(deadline=new_future).date == _date("2026-02-05")