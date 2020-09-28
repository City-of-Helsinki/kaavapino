import datetime

from django.db import models
from django.contrib.postgres.fields import ArrayField
from django.core.validators import MaxValueValidator, MinValueValidator
from django.utils.translation import ugettext_lazy as _

from users.models import PRIVILEGE_LEVELS
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

    abbreviation = models.CharField(max_length=255, verbose_name=_("abbreviation"))
    identifier = models.CharField(
        max_length=50,
        verbose_name=_("identifier"),
        db_index=True,
        unique=True,
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
        on_delete=models.CASCADE,
    )
    phase = models.ForeignKey(
        "ProjectPhase",
        verbose_name=_("phase"),
        related_name="schedule",
        on_delete=models.CASCADE,
    )
    outdated_warning = models.BooleanField(verbose_name=_("show warning when out of date"))

    @property
    def editable(self):
        if not edit_privilege:
            return False

        return True

    def __str__(self):
        return f"{self.phase} {self.deadline_type} {self.abbreviation}"


class DateType(models.Model):
    """Defines a pool of dates to calculate deadlines"""

    name = models.CharField(max_length=255)
    base_datetype = models.ManyToManyField(
        "self",
        symmetrical=False,
        verbose_name=_("base type")
    )
    business_days_only = models.BooleanField(
        default=True, verbose_name=_("do not include holidays and weekends")
    )
    dates = ArrayField(models.DateField(), verbose_name=_("dates"))
    exclude_selected = models.BooleanField(
        default=False, verbose_name=_("exclude selected dates")
    )
