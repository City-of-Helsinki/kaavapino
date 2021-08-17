import re

from django.contrib.gis.db import models
from django.utils.translation import ugettext_lazy as _
from django.contrib.postgres.fields import JSONField
from django.core.serializers.json import DjangoJSONEncoder

from projects.models import Attribute, CommonProjectPhase


class Report(models.Model):
    project_type = models.ForeignKey(
        "ProjectType",
        verbose_name=_("project type"),
        on_delete=models.CASCADE,
        related_name="reports",
    )

    name = models.CharField(max_length=255, verbose_name=_("name"))
    is_admin_report = models.BooleanField(
        verbose_name=_("can only be fetched by admin"), default=False
    )
    show_created_at = models.BooleanField(
        verbose_name=_("show created at on report"), default=False
    )
    show_modified_at = models.BooleanField(
        verbose_name=_("show modified at on report"), default=False
    )
    previewable = models.BooleanField(
        verbose_name=_("report can be previewed"), default=False
    )

    class Meta:
        verbose_name = _("report")
        verbose_name_plural = _("reports")
        ordering = ("id",)

    def __str__(self):
        return f"{self.name}"

    @property
    def filters(self):
        return Attribute.objects.filterable().filter(report_attributes__report=self)


class ReportColumn(models.Model):
    report = models.ForeignKey(
        Report,
        verbose_name=_("report"),
        on_delete=models.CASCADE,
        related_name="columns",
    )
    title = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        verbose_name=_("title"),
    )
    attributes = models.ManyToManyField(
        Attribute,
        verbose_name=_("attributes"),
        related_name="report_columns",
    )
    condition = models.ManyToManyField(
        Attribute,
        verbose_name=_("condition"),
        related_name="report_column_conditions",
        blank=True,
    )
    index = models.PositiveIntegerField(
        verbose_name=_("index"),
        default=0,
    )
    preview = models.BooleanField(
        verbose_name=_("include in preview"),
        default=True,
    )
    preview_only = models.BooleanField(
        verbose_name=_("only show in preview"),
        default=False,
    )
    custom_display_mapping = JSONField(
        default=dict,
        blank=True,
        null=True,
        encoder=DjangoJSONEncoder,
        verbose_name=_("map automatic display value strings to custom display values"),
    )

    def generate_postfix(self, project, attribute_data=None):
        postfix = self.postfixes.filter(
            phases__in=[project.phase.common_project_phase],
        ).first()

        # Fallback doesn't include data from external APIs
        attribute_data = attribute_data or project.attribute_data

        if not postfix:
            return ""

        postfix = postfix.formatting

        identifiers = re.findall(r"\{([a-zA-Z_]*)\}", postfix)
        for identifier in identifiers:
            postfix = postfix.replace(
                "{"+identifier+"}", attribute_data.get(identifier, ""),
            )

        return postfix

    class Meta:
        verbose_name = _("report column")
        verbose_name_plural = _("report columns")
        ordering = ("index",)

    def __str__(self):
        return f"{self.report} ({', '.join([attr.name for attr in self.attributes.all()])})"


class ReportColumnPostfix(models.Model):
    report_column = models.ForeignKey(
        ReportColumn,
        verbose_name=_("report column"),
        on_delete=models.CASCADE,
        related_name="postfixes",
    )
    phases = models.ManyToManyField(
        CommonProjectPhase,
        verbose_name=_("phases"),
        related_name="report_columns",
    )
    formatting = models.CharField(
        max_length=255,
        verbose_name=_("formatting"),
    )

    class Meta:
        verbose_name = _("report column postfix")
        verbose_name_plural = _("report column postfixes")
        ordering = ("id",)

    def __str__(self):
        return f"{self.formatting} ({', '.join(self.phases.all())})"
