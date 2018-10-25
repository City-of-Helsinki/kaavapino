import datetime

from django.conf import settings
from django.contrib.gis.db import models
from django.contrib.postgres.fields import JSONField
from django.core.serializers.json import DjangoJSONEncoder
from django.utils import timezone
from django.utils.translation import ugettext_lazy as _

from .attribute import Attribute


class ProjectType(models.Model):
    """Types of projects that the system supports e.g. asemakaava/city plan."""

    name = models.CharField(max_length=255, verbose_name=_("name"))

    class Meta:
        verbose_name = _("project type")
        verbose_name_plural = _("project types")
        ordering = ("name",)

    def __str__(self):
        return self.name


class Project(models.Model):
    """Represents a single project in the system."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_("user"),
        related_name="projects",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
    )
    created_at = models.DateTimeField(
        verbose_name=_("created at"), auto_now_add=True, editable=False
    )
    modified_at = models.DateTimeField(
        verbose_name=_("modified at"), auto_now=True, editable=False
    )
    name = models.CharField(max_length=255, verbose_name=_("name"))
    identifier = models.CharField(
        max_length=50,
        verbose_name=_("identifier"),
        db_index=True,
        blank=True,
        null=True,
    )
    type = models.ForeignKey(
        ProjectType,
        verbose_name=_("type"),
        related_name="projects",
        on_delete=models.PROTECT,
    )
    attribute_data = JSONField(
        verbose_name=_("attribute data"),
        default=dict,
        blank=True,
        null=True,
        encoder=DjangoJSONEncoder,
    )
    phase = models.ForeignKey(
        "ProjectPhase",
        verbose_name=_("phase"),
        null=True,
        related_name="projects",
        on_delete=models.PROTECT,
    )

    geometry = models.MultiPolygonField(null=True, blank=True)

    class Meta:
        verbose_name = _("project")
        verbose_name_plural = _("projects")
        ordering = ("name",)

    def __str__(self):
        return self.name

    def get_attribute_data(self):
        ret = {}

        for attribute in Attribute.objects.all().prefetch_related("value_choices"):
            deserialized_value = None

            if attribute.value_type == Attribute.TYPE_GEOMETRY:
                deserialized_value = self.geometry
            elif attribute.value_type == Attribute.TYPE_IMAGE:
                try:
                    deserialized_value = ProjectAttributeImage.objects.get(
                        attribute=attribute, project=self
                    ).image
                except ProjectAttributeImage.DoesNotExist:
                    deserialized_value = None
            elif attribute.identifier in self.attribute_data:
                deserialized_value = attribute.deserialize_value(
                    self.attribute_data[attribute.identifier]
                )

            ret[attribute.identifier] = deserialized_value
        return ret

    def set_attribute_data(self, data):
        self.attribute_data = {}
        self.geometry = None
        self.update_attribute_data(data)

    def update_attribute_data(self, data):
        if not isinstance(self.attribute_data, dict):
            self.attribute_data = {}

        if not data:
            return False

        attributes = {
            a.identifier: a
            for a in Attribute.objects.all().prefetch_related("value_choices")
        }

        for identifier, value in data.items():
            attribute = attributes.get(identifier)

            if not attribute:
                continue

            if attribute.value_type == Attribute.TYPE_GEOMETRY:
                self.geometry = value
            elif attribute.value_type == Attribute.TYPE_IMAGE:
                if value is False:
                    ProjectAttributeImage.objects.filter(
                        attribute=attribute, project=self
                    ).delete()
                elif value is None:
                    # None is handled in the same way as omitting this attribute from the update in the first place
                    # would have been, ie. do nothing. This is to make life easier as the form where these images
                    # mainly come from uses False for "delete" and None for "no update".
                    continue
                else:
                    ProjectAttributeImage.objects.update_or_create(
                        attribute=attribute, project=self, defaults={"image": value}
                    )
            else:
                serialized_value = attribute.serialize_value(value)

                if serialized_value is not None:
                    self.attribute_data[identifier] = serialized_value
                else:
                    self.attribute_data.pop(identifier, None)
        return True

    def get_time_line(self):
        """Produce data for a timeline graph for the given project."""
        timeline = [
            {
                "content": "Luontipvm",
                "start": self.created_at,
                "group": self.id,
                "type": "point",
            }
        ]

        for log_entry in self.phase_logs.order_by("created_at"):
            timeline.append(
                {
                    # 'title': None,
                    "content": log_entry.phase.name,
                    "start": log_entry.created_at,
                    "end": None,
                    "group": self.id,
                    "type": "background",
                    "className": log_entry.phase.color,
                }
            )

            if timeline[-2]["type"] == "background":
                timeline[-2]["end"] = log_entry.created_at

        if timeline[-1]["type"] == "background" and not timeline[-1]["end"]:
            timeline[-1]["end"] = timezone.now()

        for attribute in Attribute.objects.filter(value_type=Attribute.TYPE_DATE):
            if (
                attribute.identifier in self.attribute_data
                and self.attribute_data[attribute.identifier]
            ):
                start_dt = attribute.deserialize_value(
                    self.attribute_data[attribute.identifier]
                )

                timeline.append(
                    {
                        "type": "point",
                        "content": attribute.name,
                        "start": start_dt,
                        "group": self.id,
                    }
                )

                # TODO: Remove hard-coded logic
                if attribute.identifier == "oas_aineiston_esillaoloaika_alkaa":
                    timeline.append(
                        {
                            "type": "point",
                            "content": "OAS-paketin määräaika",
                            "start": start_dt - datetime.timedelta(weeks=2),
                            "group": self.id,
                        }
                    )

                if (
                    attribute.identifier
                    == "ehdotuksen_suunniteltu_lautakuntapaivamaara_arvio"
                    and "prosessin_kokoluokka" in self.attribute_data
                ):
                    weeks = (
                        6
                        if self.attribute_data["prosessin_kokoluokka"] in ["l", "xl"]
                        else 14
                    )

                    timeline.append(
                        {
                            "type": "point",
                            "content": "Lautakuntapaketin määräaika",
                            "start": start_dt - datetime.timedelta(weeks=weeks),
                            "group": self.id,
                        }
                    )

        return timeline


class ProjectPhase(models.Model):
    """Describes a phase of a certain project type."""

    project_type = models.ForeignKey(
        ProjectType,
        verbose_name=_("project type"),
        on_delete=models.CASCADE,
        related_name="phases",
    )
    name = models.CharField(max_length=255, verbose_name=_("name"))
    color = models.CharField(max_length=64, verbose_name=_("color"), blank=True)
    color_code = models.CharField(
        max_length=10, verbose_name=_("color code"), blank=True
    )
    index = models.PositiveIntegerField(verbose_name=_("index"))

    class Meta:
        verbose_name = _("project phase")
        verbose_name_plural = _("project phases")
        ordering = ("index",)

    def __str__(self):
        return self.name


class ProjectPhaseLog(models.Model):
    """Records project phase changes."""

    project = models.ForeignKey(
        "Project",
        verbose_name=_("project"),
        related_name="phase_logs",
        on_delete=models.CASCADE,
    )
    phase = models.ForeignKey(
        ProjectPhase,
        verbose_name=_("phase"),
        related_name="phase_logs",
        on_delete=models.CASCADE,
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_("user"),
        related_name="phase_logs",
        on_delete=models.PROTECT,
    )
    created_at = models.DateTimeField(
        verbose_name=_("created at"), auto_now_add=True, editable=False
    )

    class Meta:
        verbose_name = _("project phase log entry")
        verbose_name_plural = _("project phase log entries")
        ordering = ("created_at",)

    def __str__(self):
        return "{} {} {}".format(self.project.name, self.phase.name, self.created_at)


class ProjectPhaseSection(models.Model):
    """Defines a section within a project phase."""

    phase = models.ForeignKey(
        ProjectPhase,
        verbose_name=_("phase"),
        related_name="sections",
        on_delete=models.CASCADE,
    )
    name = models.CharField(max_length=255, verbose_name=_("name"))
    index = models.PositiveIntegerField(verbose_name=_("index"))
    attributes = models.ManyToManyField(
        Attribute,
        verbose_name=_("attributes"),
        related_name="phase_sections",
        through="ProjectPhaseSectionAttribute",
    )

    class Meta:
        verbose_name = _("project phase section")
        verbose_name_plural = _("project phase sections")
        ordering = ("index",)

    def __str__(self):
        return self.name

    def get_attribute_identifiers(self):
        return [a.identifier for a in self.attributes.all()]


class ProjectPhaseSectionAttribute(models.Model):
    """Links an attribute into a project phase section."""

    attribute = models.ForeignKey(
        Attribute, verbose_name=_("attribute"), on_delete=models.CASCADE
    )
    section = models.ForeignKey(
        ProjectPhaseSection, verbose_name=_("phase section"), on_delete=models.CASCADE
    )
    generated = models.BooleanField(verbose_name=_("generated"), default=False)
    required = models.BooleanField(verbose_name=_("required"))
    index = models.PositiveIntegerField(verbose_name=_("index"))

    relies_on = models.ForeignKey(
        "self",
        verbose_name=_("relies on"),
        on_delete=models.CASCADE,
        blank=True,
        null=True,
    )

    class Meta:
        verbose_name = _("project phase section attribute")
        verbose_name_plural = _("project phase section attributes")
        ordering = ("index",)

    def __str__(self):
        return "{} {} {} {}".format(
            self.attribute, self.section, self.section.phase, self.index
        )


class ProjectAttributeImage(models.Model):
    """Project attribute value that is an image."""

    attribute = models.ForeignKey(
        Attribute,
        verbose_name=_("attribute"),
        related_name="images",
        on_delete=models.CASCADE,
    )
    project = models.ForeignKey(
        Project,
        verbose_name=_("project"),
        related_name="images",
        on_delete=models.CASCADE,
    )
    image = models.ImageField(verbose_name=_("image"))

    class Meta:
        verbose_name = _("project attribute image")
        verbose_name_plural = _("project attribute images")

    def __str__(self):
        return "{} {}".format(self.project, self.attribute)
