from datetime import datetime
from django.conf import settings
from django.contrib.gis.db import models
from django.utils.translation import ugettext_lazy as _


class ProjectComment(models.Model):
    """Comment made in a project."""

    project = models.ForeignKey(
        "Project",
        verbose_name=_("project"),
        related_name="comments",
        on_delete=models.PROTECT,
    )

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_("user"),
        related_name="comments",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
    )

    generated = models.BooleanField(verbose_name=_("generated"), default=False)

    created_at = models.DateTimeField(
        verbose_name=_("created at"), auto_now_add=True, editable=False
    )
    modified_at = models.DateTimeField(
        verbose_name=_("modified at"), auto_now=True, editable=False
    )

    content = models.TextField(verbose_name=_("content"))

    class Meta:
        verbose_name = _("project comment")
        verbose_name_plural = _("project comments")
        ordering = ("created_at",)

    def __str__(self):
        return f"Comment {self.project} {self.created_at}"


class FieldComment(models.Model):
    """Comment made in a project."""

    project = models.ForeignKey(
        "Project",
        verbose_name=_("project"),
        related_name="field_comments",
        on_delete=models.PROTECT,
    )

    field = models.ForeignKey(
        "Attribute",
        verbose_name=_("field"),
        related_name="comments",
        on_delete=models.PROTECT,
    )

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_("user"),
        null=True,
        blank=True,
        on_delete=models.PROTECT,
    )

    generated = models.BooleanField(verbose_name=_("generated"), default=False)

    created_at = models.DateTimeField(
        verbose_name=_("created at"), auto_now_add=True, editable=False
    )
    modified_at = models.DateTimeField(
        verbose_name=_("modified at"), auto_now=True, editable=False
    )

    content = models.TextField(verbose_name=_("content"))

    class Meta:
        verbose_name = _("field comment")
        verbose_name_plural = _("field comments")
        ordering = ("created_at",)

    def __str__(self):
        return f"Comment {self.project} {self.field} {self.created_at}"


class LastReadTimestamp(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_("user"),
        null=False,
        on_delete=models.CASCADE,
    )

    project = models.ForeignKey(
        "Project",
        verbose_name=_("project"),
        null=False,
        on_delete=models.CASCADE,
    )

    timestamp = models.DateTimeField(
        verbose_name=_("timestamp"), default=datetime.now
    )

    class Meta:
        verbose_name = _("last read timestamp")
        verbose_name_plural = _("last read timestamps")
        unique_together = ("user", "project")
