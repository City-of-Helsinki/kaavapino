from django.db import models
from django.utils.translation import gettext_lazy as _
from django.utils import timezone

from projects.models import Attribute

import logging

log = logging.getLogger(__name__)


class FooterLink(models.Model):
    link_text = models.CharField(max_length=255, verbose_name=_("link text"))
    url = models.CharField(max_length=255, verbose_name=_("url"))
    index = models.PositiveIntegerField(verbose_name=_("index"), default=0)
    section = models.ForeignKey(
        "FooterSection",
        verbose_name=_("section"),
        related_name="links",
        null=False,
        on_delete=models.CASCADE,
    )

    class Meta:
        verbose_name = _("footer link")
        verbose_name_plural = _("footer links")
        ordering = ("index",)

    def __str__(self):
        return self.link_text


class FooterSection(models.Model):
    title = models.CharField(max_length=255, verbose_name=_("title"))
    index = models.PositiveIntegerField(verbose_name=_("index"), default=0)

    admin_description = "Sivuston alaosan linkit"


    class Meta:
        verbose_name = _("footer section")
        verbose_name_plural = _("footer sections")
        ordering = ("index",)

    def __str__(self):
        return self.title


class ListViewAttributeColumn(models.Model):
    """Defines custom ordering of attribute columns in project list view"""
    index = models.PositiveIntegerField(default=0)
    attribute = models.OneToOneField( \
        Attribute, primary_key=True, on_delete=models.CASCADE)

    admin_description = "Projektilistasa näkyvät sarakkeet"

    class Meta(object):
        verbose_name = _("list view attribute column")
        verbose_name_plural = _("list view attribute columns")
        ordering = ("index",)


class TargetFloorArea(models.Model):
    """Defines a yearly floor area target"""
    year = models.IntegerField(
        unique=True,
        verbose_name=_("year"),
    )
    target = models.IntegerField(
        verbose_name=_("area target"),
    )

    admin_description = "Vuositavoitteiden lisääminen ja muokkaaminen"

    def __str__(self):
        return f"{self.year}: {self.target}"

    class Meta:
        verbose_name = _("Asuinkerrosalan vuositavoite")
        verbose_name_plural = _("Asuinkerrosalan vuositavoitteet")


class ExcelFile(models.Model):
    TYPE_ATTRIBUTES = "attributes"
    TYPE_DEADLINES = "deadlines"
    TYPE_UNKNOWN = "unknown"

    TYPE_CHOICES = (
        (TYPE_ATTRIBUTES, TYPE_ATTRIBUTES),
        (TYPE_DEADLINES, TYPE_DEADLINES),
        (TYPE_UNKNOWN, TYPE_UNKNOWN)
    )

    STATUS_INACTIVE = "inactive"
    STATUS_UPDATING = "updating"
    STATUS_ACTIVE = "active"
    STATUS_ERROR = "error"

    STATUS_CHOICES = (
        (STATUS_INACTIVE, STATUS_INACTIVE),
        (STATUS_UPDATING, STATUS_UPDATING),
        (STATUS_ACTIVE, STATUS_ACTIVE),
        (STATUS_ERROR, STATUS_ERROR),
    )

    file = models.FileField(
        upload_to="excel_files/", null=False, unique=True
    )
    uploaded = models.DateTimeField(
        verbose_name=_("upload date"), auto_now_add=True
    )
    type = models.CharField(
        max_length=32, choices=TYPE_CHOICES, default=TYPE_UNKNOWN
    )
    status = models.CharField(
        max_length=32, choices=STATUS_CHOICES, default=STATUS_INACTIVE
    )
    updated = models.DateTimeField(
        verbose_name=_("update date"), null=True
    )
    options = models.CharField(
        max_length=32, null=True, default='{"kv":"1.0"}'
    )
    task_id = models.CharField(
        max_length=64, null=True
    )
    error = models.CharField(
        max_length=2048, null=True
    )

    def set_status(self, status):
        self.status = status
        self.updated = timezone.now()

    def set_error(self, error):
        if error and len(error) > 2048:
            log.warning('Error length exceeded 2048 chars, splicing error')
            error = error[:2048]
        self.error = error

    def update(self, status=None, error=None, task_id=None):
        self.set_status(status)
        self.set_error(error)
        self.task_id = task_id
        self.save()