import datetime
from calendar import isleap
from workalendar.core import MON, TUE, WED, THU, FRI, SAT, SUN
from workalendar.europe import Finland

from django.db import models
from django.contrib.postgres.fields import ArrayField
from django.core.validators import MaxValueValidator, MinValueValidator
from django.core.exceptions import ValidationError
from django.utils.translation import ugettext_lazy as _

from users.models import PRIVILEGE_LEVELS
from . import Attribute
from .helpers import DATE_SERIALIZATION_FORMAT, validate_identifier


class Deadline(models.Model):
    """Defines a common deadline type shared by multiple projects."""

    TYPE_START_POINT = "start_point"
    TYPE_END_POINT = "end_point"
    TYPE_MILESTONE = "milestone"

    TYPE_CHOICES = (
        (TYPE_START_POINT, _("start point")),
        (TYPE_END_POINT, _("end point")),
        (TYPE_MILESTONE, _("milestone")),
    )

    abbreviation = models.CharField(
        max_length=255,
        verbose_name=_("abbreviation"),
    )
    identifier = models.CharField(
        max_length=50,
        verbose_name=_("identifier"),
        validators=[validate_identifier],
    )
    edit_privilege = models.CharField(
        default=None, null=True, blank=True, max_length=6, choices=PRIVILEGE_LEVELS
    )
    deadline_type = models.CharField(
        max_length=64, verbose_name=_("deadline type"), choices=TYPE_CHOICES
    )
    date_type = models.ForeignKey(
        "DateType",
        verbose_name=_("date type"),
        on_delete=models.PROTECT,
    )
    condition_attributes = models.ManyToManyField(
        Attribute,
        verbose_name=_("show if any attribute is set"),
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
    distance_reference_deadlines = models.ManyToManyField(
        "Deadline",
        related_name="distance_reference_to",
        verbose_name=_("reference deadline(s) for minimum distance"),
        blank=True,
    )
    min_distance = models.IntegerField(
        default=0,
        verbose_name=_("minimum distance from closest applicable reference deadline"),
    )
    error_past_due = models.TextField(
        verbose_name=_("error message for past due date"),
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
    index = models.PositiveIntegerField(
        verbose_name=_("index"),
        default=0,
    )

    @property
    def editable(self):
        if not self.edit_privilege:
            return False

        return True

    @property
    def automatic(self):
        return bool(self.update_calculations.count())

    def _calculate(self, project, calculations):
        def condition_result(calculation):
            if not calculation.conditions.count():
                return True

            for condition in calculation.conditions.all():
                if project.attribute_data.get(condition):
                    return True

            return False

        # Use first calculation whose condition is met
        for calculation in calculations:
            if condition_result(calculation):
                return calculation.datecalculation.calculate(project)

        return None

    def calculate_initial(self, project):
        return self._calculate(project, self.initial_calculations.all())

    def calculate_updated(self, project):
        return self._calculate(project, self.update_calculations.all())

    def __str__(self):
        return f"{self.phase} {self.deadline_type} {self.abbreviation}"

    class Meta:
        unique_together = (
            ("abbreviation", "subtype"),
            ("identifier", "subtype"),
        )
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

    def get_dates(self, year):
        listed_dates = [date for date in self.dates]

        for automatic_date in self.automatic_dates.all():
            listed_dates += automatic_date.calculate(
                self.business_days_only, year
            )

        if self.exclude_selected:
            return [
                datetime.date(year, 1, 1) + datetime.timedelta(days=i)
                for i in range((366 if isleap(+year) else 365))
                if date + datetime.timedelta(days=i) not in listed_dates
            ]
        else:
            return listed_dates

    def valid_days_from(self, orig_date, days):
        year = orig_date.year
        dates = sorted(self.get_dates(year))

        if days < 0:
            dates = [date for date in dates if date >= orig_date]
            dates.reverse()
            print(dates)
        else:
            dates = [date for date in dates if date <= orig_date]

        # Handle the case where there aren't enough days left in the year
        while abs(days) >= len(dates):
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

        return dates[abs(days)]

    def is_valid_date(self, date):
        return date in self.get_dates(date.year)


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

    def validate_date(date):
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

    def calculate(self, business_days_only, year=datetime.datetime.now().year):
        cal = Finland()
        holidays = dict([(name, date) for date, name in cal.holidays(year)])
        holidays_next = dict([(name, date) for date, name in cal.holidays(year+1)])
        holidays_previous = dict([(name, date) for date, name in cal.holidays(year-1)])

        def get_closest_weekday(date, previous=False):
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

        def get_weekdays_in_range(start_date, end_date):
            if business_days_only:
                weekdays = [weekday for weekday in self.weekdays if weekday < SAT]
                if not weekdays:
                    return []
            else:
                weekdays = self.weekdays

            date = start_date
            return_dates = []

            while date <= end_date:
                ignore_as_holiday = business_days_only and cal.is_holiday(date)

                if not ignore_as_holiday and date.weekday() in weekdays:
                    return_dates.append(date)

                date += datetime.timedelta(days=1)

            return return_dates

        def parse_date(date, year=year):
            [day, month] = str.split(date, ".")[:2]
            return datetime.date(year, month, day)

        return_dates = []

        if self.week:
            start_date = datetime.datetime.strptime(f"{year}-W{self.week}-1", "%G-W%V-%u")
            end_date = datetime.datetime.strptime(f"{year}-W{self.week}-7", "%G-W%V-%u")
            return_dates = get_weekdays_in_range(start_date, end_date)
        elif self.start_date and self.end_date:
            start = parse_date(start_date)
            end = parse_date(end_date)
            if start > end:
                return_dates = \
                    get_weekdays_in_range(datetime.date(year, 1, 1), end) + \
                    get_weekdays_in_range(start, datetime.date(year, 12, 31))
            else:
                return_dates = get_weekdays_in_range(start, end)
        elif self.start_date:
            return_dates = [
                get_closest_weekday(parse_date(self.start_date, year-1)),
                get_closest_weekday(parse_date(self.start_date)),
            ]
        elif self.end_date:
            return_dates = [
                get_closest_weekday(parse_date(self.end_date), previous=True),
                get_closest_weekday(parse_date(self.end_date, year+1), previous=True),
            ]
        elif self.before_holiday:
            return_dates = [
                get_closest_weekday(holidays[self.before_holiday], previous=True),
                get_closest_weekday(holidays_next[self.before_holiday], previous=True),
            ]
        elif self.after_holiday:
            return_dates = [
                get_closest_weekday(holidays_previous[self.after_holiday]),
                get_closest_weekday(holidays[self.after_holiday]),
            ]

        return list(filter(lambda date: date is not None and date.year == year, return_dates))

    def clean(self):
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


class DateCalculation(models.Model):
    pass
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
        on_delete=models.PROTECT,
    )
    base_date_deadline = models.ForeignKey(
        Deadline,
        verbose_name=_("relies on date from deadline"),
        blank=True,
        null=True,
        on_delete=models.PROTECT,
    )
    constant = models.IntegerField(
        verbose_name=_("days to add"),
        blank=True,
        null=True,
    )

    def calculate(self, project):
        if self.base_date_attribute:
            date = project.attribute_data.get(
                self.base_date_attribute,
                project.created_at.date(),
            )
        elif self.base_date_deadline:
            date = project.deadlines.get(
                self.base_date_deadline,
                project.created_at.date(),
            )
        else:
            date = project.created_at.date()

        date += datetime.timedelta(days=self.constant)

        for attribute in self.attributes.all():
            try:
                date += datetime.timedelta(
                    days=project.attribute_data.get(attribute.identifier, 0)
                )
            except TypeError:
                pass

        return date

    def __str__(self):
        return self.description


class DateCalculationAttribute(models.Model):
    attribute = models.ForeignKey(
        Attribute,
        verbose_name=_("relies on date from attribute"),
        on_delete=models.PROTECT,
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
        verbose_name=_("use rule if any attribute is set"),
        blank=True,
    )
    index = models.PositiveIntegerField(
        verbose_name=_("index"),
        default=0,
    )

    class Meta:
        ordering = ("index",)
