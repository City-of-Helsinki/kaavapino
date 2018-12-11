from django.contrib.gis.db import models
from django.template.defaultfilters import slugify
from django.utils.translation import ugettext_lazy as _


class Report(models.Model):

    project_type = models.ForeignKey(
        "ProjectType",
        verbose_name=_("project type"),
        on_delete=models.CASCADE,
        related_name="reports",
    )

    name = models.CharField(max_length=255, verbose_name=_("name"))

    class Meta:
        verbose_name = _("report")
        verbose_name_plural = _("reports")
        ordering = ("id",)

    def __str__(self):
        return f"{self.name}"

    def save(self, *args, **kwargs):
        self.slug = slugify(self.name)
        return super().save(*args, **kwargs)


class ReportAttribute(models.Model):

    report = models.ForeignKey(
        Report,
        verbose_name=_("report"),
        on_delete=models.CASCADE,
        related_name="report_attributes",
    )

    attribute = models.ForeignKey(
        "Attribute",
        verbose_name=_("attribute"),
        related_name="report_attributes",
        on_delete=models.CASCADE,
    )

    class Meta:
        verbose_name = _("report attribute")
        verbose_name_plural = _("report attributes")
        unique_together = ("report", "attribute")
        ordering = ("id",)

    def __str__(self):
        return f"{self.report.name} ({self.attribute.name})"
