import datetime
import itertools

from django.conf import settings
from django.contrib.gis.db import models
from django.contrib.postgres.fields import JSONField, ArrayField
from django.core.serializers.json import DjangoJSONEncoder
from django.urls import reverse_lazy
from django.utils import timezone
from django.utils.translation import ugettext_lazy as _
from private_storage.fields import PrivateFileField

from projects.models.utils import KaavapinoPrivateStorage, arithmetic_eval
from .attribute import Attribute


class BaseAttributeMatrixStructure(models.Model):
    column_names = ArrayField(models.CharField(max_length=255))
    row_names = ArrayField(models.CharField(max_length=255))

    class Meta:
        abstract = True


class BaseAttributeMatrixCell(models.Model):
    row = models.IntegerField()
    column = models.IntegerField()

    class Meta:
        abstract = True


class ProjectType(models.Model):
    """Types of projects that the system supports e.g. asemakaava/city plan."""

    name = models.CharField(max_length=255, verbose_name=_("name"))
    metadata = JSONField(
        verbose_name=_("metadata"),
        default=dict,
        blank=True,
        null=True,
        encoder=DjangoJSONEncoder,
    )

    class Meta:
        verbose_name = _("project type")
        verbose_name_plural = _("project types")
        ordering = ("name",)

    def __str__(self):
        return self.name


class ProjectSubtype(models.Model):
    project_type = models.ForeignKey(
        ProjectType,
        verbose_name=_("project type"),
        on_delete=models.CASCADE,
        related_name="subtypes",
    )

    name = models.CharField(max_length=255, verbose_name=_("name"))
    metadata = JSONField(
        verbose_name=_("metadata"),
        default=dict,
        blank=True,
        null=True,
        encoder=DjangoJSONEncoder,
    )
    index = models.PositiveIntegerField(verbose_name=_("index"), default=0)

    class Meta:
        verbose_name = _("project subtype")
        verbose_name_plural = _("project subtypes")
        ordering = ("index",)

    def __str__(self):
        return self.name


class Project(models.Model):
    """Represents a single project in the system."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_("user"),
        related_name="projects",
        on_delete=models.PROTECT,
    )
    created_at = models.DateTimeField(
        verbose_name=_("created at"), auto_now_add=True, editable=False
    )
    modified_at = models.DateTimeField(
        verbose_name=_("modified at"), auto_now=True, editable=False
    )
    name = models.CharField(
        verbose_name=_("name"),
        max_length=255,
        unique=True,
    )
    identifier = models.CharField(
        max_length=50,
        verbose_name=_("identifier"),
        db_index=True,
        blank=True,
        null=True,
    )
    subtype = models.ForeignKey(
        ProjectSubtype,
        verbose_name=_("subtype"),
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
    deadlines = JSONField(
        verbose_name=_("deadlines"),
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
    create_principles = models.BooleanField(
        verbose_name=_("create principles"),
        default=False,
    )
    create_draft = models.BooleanField(
        verbose_name=_("create draft"),
        default=False,
    )
    public = models.BooleanField(default=True)
    archived = models.BooleanField(default=False)
    onhold = models.BooleanField(default=False)

    class Meta:
        verbose_name = _("project")
        verbose_name_plural = _("projects")
        ordering = ("name",)

    def __str__(self):
        return self.name

    def get_attribute_data(self):
        """Returns deserialized attribute data for the project."""
        ret = {}

        for attribute in Attribute.objects.all().prefetch_related("value_choices"):
            deserialized_value = None

            if attribute.value_type == Attribute.TYPE_GEOMETRY:
                geometry = ProjectAttributeMultipolygonGeometry.objects.filter(
                    attribute=attribute, project=self
                ).first()
                if not geometry:
                    continue
                deserialized_value = geometry.geometry
            elif attribute.value_type in [Attribute.TYPE_IMAGE, Attribute.TYPE_FILE]:
                try:
                    deserialized_value = ProjectAttributeFile.objects.get(
                        attribute=attribute, project=self
                    ).file
                except ProjectAttributeFile.DoesNotExist:
                    deserialized_value = None
            elif attribute.identifier in self.attribute_data:
                deserialized_value = attribute.deserialize_value(
                    self.attribute_data[attribute.identifier]
                )

            ret[attribute.identifier] = deserialized_value
        return ret

    def set_attribute_data(self, data):
        self.attribute_data = {}
        self.update_attribute_data(data)

    def update_attribute_data(self, data):
        if not isinstance(self.attribute_data, dict):
            self.attribute_data = {}

        if not data:
            return False

        phase_section_attrs = Attribute.objects.filter(
            phase_sections__phase__project_subtype__projects=self
        )
        floor_area_section_attrs = Attribute.objects.filter(
            floor_area_sections__project_subtype__projects=self
        )
        project_attributes = (
            (phase_section_attrs | floor_area_section_attrs)
            .distinct()
            .prefetch_related("value_choices")
        )

        generated_attributes = project_attributes.filter(generated=True)

        attributes = {a.identifier: a for a in project_attributes}

        for identifier, value in data.items():
            attribute = attributes.get(identifier)

            if not attribute:
                continue

            if attribute.value_type == Attribute.TYPE_GEOMETRY:
                geometry_query_params = {"attribute": attribute, "project": self}
                if not value:
                    ProjectAttributeMultipolygonGeometry.objects.filter(
                        **geometry_query_params
                    ).delete()
                else:
                    ProjectAttributeMultipolygonGeometry.objects.update_or_create(
                        **geometry_query_params, defaults={"geometry": value}
                    )
            elif attribute.value_type in [Attribute.TYPE_IMAGE, Attribute.TYPE_FILE]:
                if not value:
                    ProjectAttributeFile.objects.filter(
                        attribute=attribute, project=self
                    ).delete()
                    self.attribute_data.pop(identifier, None)
            elif attribute.value_type == Attribute.TYPE_FIELDSET:
                serialized_value = attribute.serialize_value(value)
                if not serialized_value:
                    self.attribute_data.pop(identifier, None)
                else:
                    self.attribute_data[identifier] = serialized_value
            else:
                serialized_value = attribute.serialize_value(value)

                if serialized_value is not None:
                    self.attribute_data[identifier] = serialized_value
                else:
                    self.attribute_data.pop(identifier, None)

        self.update_generated_values(generated_attributes, self.attribute_data)

        return True

    def update_generated_values(self, generated_attributes, attribute_data):
        for attribute in generated_attributes:
            calculation_operators = attribute.calculation_operators
            attribute_values = [
                attribute_data.get(identifier, 0) or 0
                for identifier in attribute.calculation_attribute_identifiers
            ]

            calculation_string = "".join(
                [
                    str(value) + (operator or "")
                    for value, operator in itertools.zip_longest(
                        attribute_values, calculation_operators
                    )
                ]
            )

            try:
                calculated_value = arithmetic_eval(calculation_string)
            except (ValueError, KeyError, ZeroDivisionError):
                # Value errors are thrown for
                calculated_value = 0

            attribute_data[attribute.identifier] = calculated_value

    def set_default_deadlines(self):
        phases = self.subtype.phases.all().order_by("index")

        deadlines = []

        now = timezone.now()
        previous_phase_ends = now
        for phase in phases:
            deadline = now
            weeks_delta = phase.metadata.get("default_end_weeks_delta", None)
            if weeks_delta:
                deadline = previous_phase_ends + timezone.timedelta(weeks=weeks_delta)
            deadlines.append(
                {
                    "phase_id": phase.id,
                    "phase_name": phase.name,
                    "start": previous_phase_ends,
                    "deadline": deadline,
                }
            )
            previous_phase_ends = deadline

        self.deadlines = deadlines
        self.save()

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

    @property
    def type(self):
        return self.subtype.project_type

    @property
    def pino_number(self):
        return str(self.pk).zfill(7)


class ProjectFloorAreaSection(models.Model):
    """Defines a floor area data section."""

    project_subtype = models.ForeignKey(
        ProjectSubtype,
        verbose_name=_("project subtype"),
        on_delete=models.CASCADE,
        related_name="floor_area_sections",
    )
    name = models.CharField(max_length=255, verbose_name=_("name"))
    index = models.PositiveIntegerField(verbose_name=_("index"), default=0)
    attributes = models.ManyToManyField(
        Attribute,
        verbose_name=_("attributes"),
        related_name="floor_area_sections",
        through="ProjectFloorAreaSectionAttribute",
    )

    class Meta:
        verbose_name = _("project floor area section")
        verbose_name_plural = _("project floor area sections")
        ordering = ("index",)

    def __str__(self):
        return f"{self.name} ({self.project_subtype.name})"

    def get_attribute_identifiers(self):
        return [a.identifier for a in self.attributes.all()]


class ProjectFloorAreaSectionAttribute(models.Model):
    """Links an attribute into a project floor area section."""

    attribute = models.ForeignKey(
        Attribute, verbose_name=_("attribute"), on_delete=models.CASCADE
    )
    section = models.ForeignKey(
        ProjectFloorAreaSection,
        verbose_name=_("floor area section"),
        on_delete=models.CASCADE,
    )
    index = models.PositiveIntegerField(verbose_name=_("index"), default=0)

    relies_on = models.ForeignKey(
        "self",
        verbose_name=_("relies on"),
        on_delete=models.CASCADE,
        blank=True,
        null=True,
    )

    class Meta:
        verbose_name = _("project floor area section attribute")
        verbose_name_plural = _("project floor area section attributes")
        ordering = ("index",)

    def __str__(self):
        return f"{self.attribute} {self.section} {self.index}"


class ProjectFloorAreaSectionAttributeMatrixStructure(BaseAttributeMatrixStructure):
    section = models.ForeignKey(
        ProjectFloorAreaSection, verbose_name=_("phase section"), on_delete=models.CASCADE
    )

    def __str__(self):
        return f"{self.section} ({len(self.row_names)}x{len(self.column_names)})"


class ProjectFloorAreaSectionAttributeMatrixCell(BaseAttributeMatrixCell):
    attribute = models.ForeignKey(
        ProjectFloorAreaSectionAttribute, on_delete=models.CASCADE
    )
    structure = models.ForeignKey(
        ProjectFloorAreaSectionAttributeMatrixStructure, on_delete=models.CASCADE
    )

    def __str__(self):
        return f"{self.structure} {self.attribute} ({self.row}, {self.column})"


class ProjectPhase(models.Model):
    """Describes a phase of a certain project subtype."""

    project_subtype = models.ForeignKey(
        ProjectSubtype,
        verbose_name=_("project subtype"),
        on_delete=models.CASCADE,
        related_name="phases",
    )
    name = models.CharField(max_length=255, verbose_name=_("name"))
    color = models.CharField(max_length=64, verbose_name=_("color"), blank=True)
    color_code = models.CharField(
        max_length=10, verbose_name=_("color code"), blank=True
    )
    index = models.PositiveIntegerField(verbose_name=_("index"), default=0)

    metadata = JSONField(
        verbose_name=_("metadata"),
        default=dict,
        blank=True,
        null=True,
        encoder=DjangoJSONEncoder,
    )

    class Meta:
        verbose_name = _("project phase")
        verbose_name_plural = _("project phases")
        ordering = ("index",)

    def __str__(self):
        return f"{self.name} ({self.project_subtype.name})"

    @property
    def project_type(self):
        return self.project_subtype.project_type


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
        return f"{self.project.name} {self.phase.name} {self.created_at}"


class ProjectPhaseSection(models.Model):
    """Defines a section within a project phase."""

    phase = models.ForeignKey(
        ProjectPhase,
        verbose_name=_("phase"),
        related_name="sections",
        on_delete=models.CASCADE,
    )
    name = models.CharField(max_length=255, verbose_name=_("name"))
    index = models.PositiveIntegerField(verbose_name=_("index"), default=0)
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
        return f"{self.name} ({self.phase.name}, {self.phase.project_subtype.name})"

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
    index = models.PositiveIntegerField(verbose_name=_("index"), default=0)

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
        return f"{self.attribute} {self.section} {self.section.phase} {self.index}"


class ProjectAttributeFile(models.Model):
    """Project attribute value that is an file."""

    attribute = models.ForeignKey(
        Attribute,
        verbose_name=_("attribute"),
        related_name="files",
        on_delete=models.CASCADE,
    )
    project = models.ForeignKey(
        Project,
        verbose_name=_("project"),
        related_name="files",
        on_delete=models.CASCADE,
    )

    description = models.TextField(verbose_name=_("description"), null=True, blank=True)

    def get_upload_subfolder(self):
        project_id = str(self.project.pk)
        if not project_id:
            raise ValueError("No project id could be found, can't save file!")
        return ["projects", project_id, self.attribute.identifier]

    file = PrivateFileField(
        "File",
        storage=KaavapinoPrivateStorage(
            base_url=reverse_lazy("serve_private_project_file", kwargs={"path": ""}),
            url_postfix="projects",
        ),
        upload_subfolder=get_upload_subfolder,
        max_length=255,
    )

    class Meta:
        verbose_name = _("project attribute file")
        verbose_name_plural = _("project attribute files")

    def __str__(self):
        return f"{self.project} {self.attribute}"


class PhaseAttributeMatrixStructure(BaseAttributeMatrixStructure):
    section = models.ForeignKey(
        ProjectPhaseSection, verbose_name=_("phase section"), on_delete=models.CASCADE
    )

    def __str__(self):
        return f"{self.section} ({len(self.row_names)}x{len(self.column_names)})"


class PhaseAttributeMatrixCell(BaseAttributeMatrixCell):
    attribute = models.ForeignKey(
        ProjectPhaseSectionAttribute, on_delete=models.CASCADE
    )
    structure = models.ForeignKey(
        PhaseAttributeMatrixStructure, on_delete=models.CASCADE
    )

    def __str__(self):
        return f"{self.structure} {self.attribute} ({self.row}, {self.column})"


class ProjectAttributeMultipolygonGeometry(models.Model):
    geometry = models.MultiPolygonField(null=True, blank=True)
    attribute = models.ForeignKey(
        Attribute,
        verbose_name=_("attribute"),
        related_name="geometries",
        on_delete=models.CASCADE,
    )
    project = models.ForeignKey(
        Project,
        verbose_name=_("project"),
        related_name="geometries",
        on_delete=models.CASCADE,
    )
