from __future__ import annotations
from typing import TYPE_CHECKING, Optional, Any

if TYPE_CHECKING:
    from . import Project

import datetime
import logging
from calendar import isleap
from workalendar.core import MON, TUE, WED, THU, FRI, SAT, SUN
from workalendar.europe import Finland

from django.db import models
from django.contrib.postgres.fields import ArrayField
from django.core.validators import MaxValueValidator, MinValueValidator
from django.core.exceptions import ValidationError, ObjectDoesNotExist
from django.utils.translation import gettext_lazy as _

from users.models import PRIVILEGE_LEVELS
from . import Attribute
from .helpers import DATE_SERIALIZATION_FORMAT, validate_identifier

log = logging.getLogger(__name__)


class Deadline(models.Model):
    """Defines a common deadline type shared by multiple projects."""

    TYPE_PHASE_START = "phase_start"
    TYPE_PHASE_END = "phase_end"
    TYPE_DASHED_START = "dashed_start"
    TYPE_DASHED_END = "dashed_end"
    TYPE_INNER_START = "inner_start"
    TYPE_INNER_END = "inner_end"
    TYPE_MILESTONE = "milestone"

    TYPE_CHOICES = (
        (TYPE_PHASE_START, _("phase start point")),
        (TYPE_PHASE_END, _("phase end point")),
        (TYPE_DASHED_START, _("dashed line start point")),
        (TYPE_DASHED_END, _("dashed line end point")),
        (TYPE_INNER_START, _("inner line start point")),
        (TYPE_INNER_END, _("inner line end point")),
        (TYPE_MILESTONE, _("milestone")),
    )

    abbreviation = models.CharField(
        max_length=255,
        verbose_name=_("abbreviation"),
    )
    attribute = models.ForeignKey(
        "Attribute",
        verbose_name=_("attribute"),
        related_name="deadline",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
    )
    confirmation_attribute = models.ForeignKey(
        "Attribute",
        verbose_name=_("attribute for confirmation"),
        related_name="confirms_deadline",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
    )
    edit_privilege = models.CharField(
        default=None, null=True, blank=True, max_length=6, choices=PRIVILEGE_LEVELS
    )
    deadline_types = ArrayField(
        models.CharField(
            max_length=64,
            choices=TYPE_CHOICES,
        ),
        verbose_name=_("deadline types"),
        null=True,
        blank=True,
    )
    date_type = models.ForeignKey(
        "DateType",
        verbose_name=_("date type"),
        on_delete=models.PROTECT,
        blank=True,
        null=True,
    )
    condition_attributes = models.ManyToManyField(
        Attribute,
        verbose_name=_("show if any attribute is set"),
        related_name="condition_to_deadlines",
        blank=True,
    )
    phase = models.ForeignKey(
        "ProjectPhase",
        verbose_name=_("phase"),
        related_name="schedule",
        on_delete=models.CASCADE,
    )
    subtype = models.ForeignKey(
        "ProjectSubtype",
        verbose_name=_("subtype"),
        related_name="schedule",
        on_delete=models.CASCADE,
    )
    initial_calculations = models.ManyToManyField(
        "DeadlineDateCalculation",
        verbose_name=_("initial calculations"),
        related_name="generates_deadlines",
        blank=True,
    )
    update_calculations = models.ManyToManyField(
        "DeadlineDateCalculation",
        verbose_name=_("update calculations"),
        related_name="updates_deadlines",
        blank=True,
    )
    error_past_due = models.TextField(
        verbose_name=_("error message for past due date"),
        null=True,
        blank=True,
    )
    error_date_type_mismatch = models.TextField(
        verbose_name=_("error message for date type mismatch"),
        null=True,
        blank=True,
    )
    error_min_distance_previous = models.TextField(
        verbose_name=_("error message for minimum distance to previous date not met"),
        null=True,
        blank=True,
    )
    warning_min_distance_next = models.TextField(
        verbose_name=_("warning message for minimum distance to next date not met"),
        null=True,
        blank=True,
    )
    default_to_created_at = models.BooleanField(
        verbose_name=_("Use created at as value if no attribute or calculations are specified"),
        default=False,
    )
    index = models.PositiveIntegerField(
        verbose_name=_("index"),
        default=0,
    )

    admin_description = "Projektiaikataulun määräaikojen määritykset"

    @property
    def initial_depends_on(self) -> list:
        calc: DeadlineDateCalculation
        return list(set([
            calc.datecalculation.base_date_deadline
            for calc in self.initial_calculations.all().select_related("datecalculation", "datecalculation__base_date_deadline")
            if calc.datecalculation.base_date_deadline
        ]))

    @property
    def update_depends_on(self) -> list:
        calc: DeadlineDateCalculation
        return list(set([
            calc.datecalculation.base_date_deadline
            for calc in self.update_calculations.all().select_related("datecalculation", "datecalculation__base_date_deadline")
            if calc.datecalculation.base_date_deadline
        ]))

    @property
    def editable(self) -> bool:
        if not self.edit_privilege:
            return False

        return True

    def _check_condition(self, project: Project, condition: Attribute, preview_attributes: dict = {}) -> bool:
        attribute_data: dict[str, str] = {**project.attribute_data, **preview_attributes}
        if attribute_data.get(condition.identifier):
            return True
        elif condition.static_property:
            return bool(getattr(project, condition.static_property))
        else:
            return False

    def _calculate(self,
                   project: Project,
                   calculations: list[DeadlineDateCalculation],
                   datetype: DateType,
                   valid_dls: list[Deadline] = [],
                   preview_attributes: dict = {}
                   ) -> Optional[datetime.date]:
        # TODO hard-coded, maybe change later
        if self.phase.name == "Periaatteet" and not project.create_principles:
            return None
        elif self.phase.name == "Luonnos" and not project.create_draft:
            return None

        attribute_data = {**project.attribute_data, **preview_attributes}

        # Use first calculation whose condition is met
        # and target has a value
        for calculation in calculations:
            condition_result: bool = False
            base_attr: Attribute = calculation.datecalculation.base_date_attribute
            base_deadline: Deadline = calculation.datecalculation.base_date_deadline

            # When calculating previews, do not use base deadlines that will be deleted
            if base_deadline and valid_dls and base_deadline not in valid_dls:
                continue

            if base_attr and base_attr.static_property:
                base_attr = getattr(project, base_attr.static_property, None)
            elif base_attr:
                base_date = attribute_data.get(base_attr.identifier)
            elif base_deadline and base_deadline.attribute:
                try:
                    base_date = preview_attributes.get(base_deadline.attribute.identifier) or \
                        project.deadlines.get(deadline=base_deadline).date
                except ObjectDoesNotExist:
                    base_date = None
            elif base_deadline:
                try:
                    base_date = project.deadlines.get(deadline=base_deadline).date
                except ObjectDoesNotExist:
                    base_date = None
            else:
                base_date = None

            if base_date:
                if not calculation.conditions.count() + \
                    calculation.not_conditions.count():
                    condition_result = True

                for condition in calculation.conditions.all():
                    if self._check_condition(project, condition, preview_attributes):
                        condition_result = True

                for condition in calculation.not_conditions.all():
                    if not self._check_condition(project, condition, preview_attributes):
                        condition_result = True

            if condition_result:
                return calculation.datecalculation.calculate(project, datetype, preview_attributes)

        if self.default_to_created_at:
            return project.created_at.date()

        return None

    def calculate_initial(self, project: Project, preview_attributes: dict[str, Any] = {}) -> Optional[datetime.date]:
        if preview_attributes:
            valid_dls: list[Deadline] = project.get_applicable_deadlines(
                preview_attributes=preview_attributes
            )
        else:
            valid_dls: list[Deadline] = []

        return self._calculate(
            project,
            self.initial_calculations.all().select_related("datecalculation"),
            self.date_type,
            valid_dls,
            preview_attributes,
        )

    def calculate_updated(self, project: Project, preview_attributes: dict[str, Any] = {}) -> Optional[datetime.date]:
        if self.update_calculations.count():
            if preview_attributes:
                valid_dls: list[Deadline] = project.get_applicable_deadlines(
                    preview_attributes=preview_attributes
                )
            else:
                valid_dls: list[Deadline] = []

            return self._calculate(
                project,
                self.update_calculations.all().select_related("datecalculation", "datecalculation__base_date_attribute",
                                                              "datecalculation__base_date_deadline",
                                                              "datecalculation__base_date_deadline__attribute"),
                self.date_type,
                valid_dls,
                preview_attributes,
            )
        elif self.attribute:
            attribute_data: dict[str, str] = {**project.attribute_data, **preview_attributes}
            return attribute_data.get(self.attribute.identifier, None)

    def __str__(self):
        return f"{self.phase} {self.deadline_types} {self.abbreviation}"

    class Meta:
        unique_together = (
            ("abbreviation", "subtype"),
            ("attribute", "phase"),
        )
        ordering = ("index",)
        verbose_name = _("deadline")
        verbose_name_plural = _("deadlines")


class DeadlineDistance(models.Model):
    deadline = models.ForeignKey(
        "Deadline",
        related_name="distances_to_previous",
        verbose_name=_("deadline"),
        on_delete=models.CASCADE,
    )
    previous_deadline = models.ForeignKey(
        "Deadline",
        related_name="distances_to_next",
        verbose_name=_("previous deadline"),
        on_delete=models.CASCADE,
    )
    distance_from_previous = models.IntegerField(
        default=0,
        verbose_name=_("minimum distance from previous deadline"),
    )
    date_type = models.ForeignKey(
        "DateType",
        verbose_name=_("date type"),
        on_delete=models.PROTECT,
        blank=True,
        null=True,
    )
    # Only simple boolean conditions needed for now
    conditions = models.ManyToManyField(
        Attribute,
        verbose_name=_("use rule if any attribute is set"),
        blank=True,
    )
    index = models.PositiveIntegerField(
        verbose_name=_("index"),
        default=0,
    )

    def __str__(self):
        return f"{self.previous_deadline.abbreviation} -> {self.deadline.abbreviation} ({self.distance_from_previous}{' ' + str(self.date_type) if self.date_type else ''})"

    class Meta:
        ordering = ("index",)


class DateType(models.Model):
    """Defines a pool of dates to calculate deadlines"""

    identifier = models.CharField(
        max_length=255,
        db_index=True,
        unique=True,
        validators=[validate_identifier],
    )
    name = models.CharField(max_length=255)
    base_datetype = models.ManyToManyField(
        "self",
        symmetrical=False,
        verbose_name=_("base type"),
        blank=True,
    )
    business_days_only = models.BooleanField(
        default=True, verbose_name=_("do not include holidays and weekends")
    )
    dates = ArrayField(
        models.DateField(),
        verbose_name=_("dates"),
        null=True,
        blank=True,
    )
    automatic_dates = models.ManyToManyField(
        "AutomaticDate",
        verbose_name=_("automatic dates"),
        blank=True,
    )
    exclude_selected = models.BooleanField(
        default=False, verbose_name=_("exclude selected dates")
    )

    @staticmethod
    def _filter_date_list(date_list: list[datetime.date], business_days_only: bool) -> list[datetime.date]:
        cal = Finland()

        if not business_days_only:
            return date_list

        return [
            date for date in date_list
            if cal.is_working_day(date)
        ]

    def get_dates(self, year: int) -> list[datetime.date]:
        listed_dates: list[datetime.date] = self.dates or []
        base_dates: list = []
        has_base_datetypes: bool = self.base_datetype.exists()

        for base_datetype in self.base_datetype.all().prefetch_related("automatic_dates"):
            base_dates += base_datetype.get_dates(year)

        automatic_date: AutomaticDate
        for automatic_date in self.automatic_dates.all():
            listed_dates += automatic_date.calculate(
                self.business_days_only, year
            )

        if self.exclude_selected:
            def include(date: datetime.date) -> bool:
                if date not in listed_dates \
                    and has_base_datetypes \
                    and date in base_dates:
                    return True
                elif date not in listed_dates \
                    and not has_base_datetypes:
                    return True
                else:
                    return False

            return self._filter_date_list([
                datetime.date(year, 1, 1) + datetime.timedelta(days=i)
                for i in range((366 if isleap(+year) else 365))
                if include(datetime.date(year, 1, 1)+datetime.timedelta(days=i))
            ], self.business_days_only)
        else:
            return self._filter_date_list(
                listed_dates + base_dates,
                self.business_days_only,
            )

    def valid_days_to(self, date_a: datetime.date, date_b: datetime.date) -> int:
        days: int = (date_b - date_a).days
        reverse: int = 1

        # Swap a and b if b comes before a
        if days < 0:
            [date_a, date_b] = [date_b, date_a]
            reverse = -1

        # Get valid dates for all relevant years
        valid_dates: list[datetime.date] = []
        for year in range(date_a.year, date_b.year+1):
            valid_dates += self.get_dates(year)

        return len(list(filter(
            lambda x: x > date_a and x <= date_b,
            valid_dates,
        ))) * reverse

    def valid_days_from(self, orig_date: datetime.date, days: int):
        year: int = orig_date.year
        dates: list[datetime.date] = sorted(self.get_dates(year))

        is_valid: bool = self.is_valid_date(orig_date)

        if days == 0:
            if is_valid:
                return orig_date
            else:
                return None

        if days < 0:
            dates = [date for date in dates if date <= orig_date]
            dates.reverse()
        else:
            dates = [date for date in dates if date >= orig_date]

        # Handle the case where there aren't enough days left in the year
        while abs(days) > len(dates):
            if days < 0:
                days += len(dates)
                year -= 1
            else:
                days -= len(dates)
                year += 1

            # Give up after ten years
            if abs(year - orig_date.year) >= 10:
                return None

            dates = sorted(self.get_dates(year))

            if days < 0:
                dates.reverse()

        if not is_valid:
            # Special case to prevent using last index
            if days == 0:
                return dates[days]

            return dates[abs(days) - 1]

        if len(dates) == abs(days):
            return dates[abs(days) - 1]

        return dates[abs(days)]

    def is_valid_date(self, date: datetime.date) -> bool:
        return date in self.get_dates(date.year)

    def get_closest_valid_date(self, date: datetime.date) -> datetime.date:
        if self.is_valid_date(date):
            return date

        return self.valid_days_from(date, 1)

    def __str__(self):
        return self.name

    class Meta:
        verbose_name = _("date type")
        verbose_name_plural = _("date types")


class AutomaticDate(models.Model):
    """Defines logic to determine automatic recurring dates"""
    name = models.CharField(max_length=255, verbose_name=_("name"))

    WEEKDAY_CHOICES = (
        (MON, _("monday")),
        (TUE, _("tuesday")),
        (WED, _("wednesday")),
        (THU, _("thursday")),
        (FRI, _("friday")),
        (SAT, _("saturday")),
        (SUN, _("sunday")),
    )

    def get_holidays():
        cal = Finland()
        return ((holiday, _(holiday)) for __, holiday in cal.holidays())

    weekdays = ArrayField(
        models.IntegerField(choices=WEEKDAY_CHOICES),
        verbose_name=_("weekdays"),
    )

    def validate_date(date) -> None:
        validation_error = ValidationError(_("Invalid date(s): input date in dd.mm. format"))

        try:
            [day, month] = str.split(date, ".")[:2]
            day = int(day)
            month = int(month)
        except (IndexError, ValueError):
            raise validation_error

        if not 1 <= month <= 12:
            raise validation_error
        elif \
            (month == 2 and day > 29) or \
            (month in [4, 6, 9, 11] and day > 30) or \
            (day > 31):
            raise validation_error

    week = models.IntegerField(
        verbose_name=_("week number"),
        validators=[MinValueValidator(1), MaxValueValidator(53)],
        null=True,
        blank=True,
    )
    before_holiday = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        verbose_name=_("last day before holiday"),
        choices=get_holidays(),
    )
    after_holiday = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        verbose_name=_("first day after holiday"),
        choices=get_holidays(),
    )
    start_date = models.CharField(
        max_length=6,
        null=True,
        blank=True,
        verbose_name=_("start date"),
        validators=[validate_date],
    )
    end_date = models.CharField(
        max_length=6,
        null=True,
        blank=True,
        verbose_name=_("end date"),
        validators=[validate_date],
    )

    def _get_closest_weekday(self,
                             date: datetime.date,
                             business_days_only: bool,
                             previous: bool = False
                             ) -> Optional[datetime.date]:
        cal = Finland()
        if business_days_only:
            weekdays = [weekday for weekday in self.weekdays if weekday < SAT]
            if not weekdays:
                return None

            for delta in range(1, 365):
                new_date = date + datetime.timedelta(days=(-delta if previous else delta))
                if not cal.is_holiday(new_date) and new_date.weekday() in weekdays:
                    return new_date

        else:
            for delta in range(1, 365):
                new_date = date + datetime.timedelta(days=(-delta if previous else delta))
                if new_date.weekday() in self.weekdays:
                    return new_date

        return None

    def _get_weekdays_in_range(self,
                               start_date: datetime.date,
                               end_date: datetime.date,
                               business_days_only: bool
                               ) -> list[datetime.date]:
        cal = Finland()
        if business_days_only:
            weekdays = [weekday for weekday in self.weekdays if weekday < SAT]
            if not weekdays:
                return []
        else:
            weekdays = self.weekdays

        date = start_date
        return_dates: list[datetime.date] = []

        while date <= end_date:
            ignore_as_holiday = business_days_only and cal.is_holiday(date)

            if not ignore_as_holiday and date.weekday() in weekdays:
                return_dates.append(date)

            date += datetime.timedelta(days=1)

        return return_dates

    def _parse_date(self, date: str, year: int) -> datetime.date:
        [day, month] = str.split(date, ".")[:2]
        return datetime.date(year, int(month), int(day))

    def calculate(self, business_days_only: bool, year: int = datetime.datetime.now().year) -> list[datetime.date]:
        cal = Finland()
        holidays: dict[str, datetime.date] = dict(
            [(name, date) for date, name in cal.holidays(year)]
        )
        holidays_next: dict[str, datetime.date] = dict(
            [(name, date) for date, name in cal.holidays(year+1)]
        )
        holidays_previous: dict[str, datetime.date] = dict(
            [(name, date) for date, name in cal.holidays(year-1)]
        )

        return_dates: list[datetime.date] = []

        if self.week:
            start_date = datetime.datetime.strptime( \
                f"{year}-W{self.week}-1", "%G-W%V-%u").date()
            end_date = datetime.datetime.strptime( \
                f"{year}-W{self.week}-7", "%G-W%V-%u").date()
            return_dates = self._get_weekdays_in_range(
                start_date,
                end_date,
                business_days_only,
            )
        elif self.start_date and self.end_date:
            start = self._parse_date(self.start_date, year)
            end = self._parse_date(self.end_date, year)
            if start > end:
                return_dates = \
                    self._get_weekdays_in_range(
                        datetime.date(year, 1, 1),
                        end,
                        business_days_only,
                    ) + self._get_weekdays_in_range(
                        start,
                        datetime.date(year, 12, 31),
                        business_days_only,
                    )
            else:
                return_dates = self._get_weekdays_in_range(
                    start,
                    end,
                    business_days_only,
                )
        elif self.start_date:
            return_dates = [
                self._get_closest_weekday(
                    self._parse_date(self.start_date, year-1),
                    business_days_only,
                ),
                self._get_closest_weekday(
                    self._parse_date(self.start_date, year),
                    business_days_only,
                ),
            ]
        elif self.end_date:
            return_dates = [
                self._get_closest_weekday(
                    self._parse_date(self.end_date, year),
                    business_days_only,
                    previous=True,
                ),
                self._get_closest_weekday(
                    self._parse_date(self.end_date, year+1),
                    business_days_only,
                    previous=True,
                ),
            ]
        elif self.before_holiday:
            return_dates = [
                self._get_closest_weekday(
                    holidays[self.before_holiday],
                    business_days_only,
                    previous=True,
                ),
                self._get_closest_weekday(
                    holidays_next[self.before_holiday],
                    business_days_only,
                    previous=True,
                ),
            ]
        elif self.after_holiday:
            return_dates = [
                self._get_closest_weekday(
                    holidays_previous[self.after_holiday],
                    business_days_only,
                ),
                self._get_closest_weekday(
                    holidays[self.after_holiday],
                    business_days_only,
                ),
            ]

        return list(filter(lambda date: date is not None and date.year == year, return_dates))

    def clean(self) -> None:
        filled_date_fields = \
            int(bool(self.week)) + \
            int(bool(self.start_date or self.end_date)) + \
            int(bool(self.before_holiday)) + \
            int(bool(self.after_holiday))
        if filled_date_fields != 1:
            raise ValidationError(_(
                "Only use one of the following: \
                Week number, \
                end and/or start date, \
                last day before holiday, \
                first day after holiday"
            ))

    def __str__(self):
        return self.name


class DateCalculation(models.Model):
    description = models.CharField(
        max_length=255,
        blank=True,
        null=True,
    )
    base_date_attribute = models.ForeignKey(
        Attribute,
        verbose_name=_("relies on date from attribute"),
        blank=True,
        null=True,
        on_delete=models.CASCADE,
    )
    base_date_deadline = models.ForeignKey(
        Deadline,
        verbose_name=_("relies on date from deadline"),
        blank=True,
        null=True,
        on_delete=models.CASCADE,
    )
    constant = models.IntegerField(
        verbose_name=_("days to add"),
        blank=True,
        null=True,
    )
    date_type = models.ForeignKey(
        "DateType",
        verbose_name=_("date type"),
        on_delete=models.PROTECT,
        blank=True,
        null=True,
    )

    def calculate(self, project: Project, dl_datetype: DateType, preview_attributes: dict = {}):
        attribute_data: dict = {**project.attribute_data, **preview_attributes}
        date = None

        if self.base_date_attribute:
            date = attribute_data.get(
                self.base_date_attribute.identifier,
                None
            )
        elif self.base_date_deadline and self.base_date_deadline.attribute:
            try:
                date = preview_attributes.get(
                    self.base_date_deadline.attribute.identifier,
                ) or project.deadlines.get(
                    deadline = self.base_date_deadline
                ).date
            except Exception:
                date = None
        elif self.base_date_deadline:
            try:
                date = project.deadlines.get(
                    deadline = self.base_date_deadline,
                ).date
            except Exception:
                date = None

        if not date:
            return None

        if type(date) == str:
            date = datetime.datetime.strptime(date, DATE_SERIALIZATION_FORMAT).date()

        if self.date_type and date:
            date = self.date_type.valid_days_from(date, self.constant)
        elif date:
            date += datetime.timedelta(days=self.constant)

        attribute: Attribute
        for attribute in self.attributes.all():
            try:
                date += datetime.timedelta(
                    days=attribute_data.get(attribute.identifier, 0)
                )
            except TypeError:
                pass

        if dl_datetype:
            return dl_datetype.get_closest_valid_date(date)
        else:
            return date

    def __str__(self):
        return self.description or \
            f"Sum of {self.base_date_deadline or self.base_date_attribute} and {self.constant or 0}"


class DateCalculationAttribute(models.Model):
    attribute = models.ForeignKey(
        Attribute,
        verbose_name=_("relies on date from attribute"),
        on_delete=models.CASCADE,
    )
    calculation = models.ForeignKey(
        DateCalculation,
        verbose_name=_("calculation"),
        related_name="attributes",
        on_delete=models.CASCADE,
    )
    subtract = models.BooleanField(
        default=False,
        verbose_name=_("subtract"),
    )

    def __str__(self):
        return f"{'-' if self.subtract else '-'} {self.attribute}"


class DeadlineDateCalculation(models.Model):
    deadline = models.ForeignKey(
        Deadline,
        verbose_name=_("deadline"),
        on_delete=models.CASCADE,
    )
    datecalculation = models.ForeignKey(
        DateCalculation,
        verbose_name=_("date calculation"),
        on_delete=models.CASCADE,
    )
    # Only simple boolean conditions needed for now
    conditions = models.ManyToManyField(
        Attribute,
        related_name="condition_for_deadlinedatecalculation",
        verbose_name=_("use rule if any attribute is truthy"),
        blank=True,
    )
    not_conditions = models.ManyToManyField(
        Attribute,
        related_name="not_condition_for_deadlinedatecalculation",
        verbose_name=_("use rule if any attribute is falsy"),
        blank=True,
    )
    index = models.PositiveIntegerField(
        verbose_name=_("index"),
        default=0,
    )

    def __str__(self):
        return f"{self.datecalculation} ({self.deadline})"

    class Meta:
        ordering = ("index",)
