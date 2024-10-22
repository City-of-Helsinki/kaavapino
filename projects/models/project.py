import datetime
import itertools
import logging

from actstream import action
from actstream.models import Action as ActStreamAction
from django.conf import settings
from django.contrib.admin.models import LogEntry
from django.contrib.gis.db import models
from django.contrib.postgres.fields import ArrayField
from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.search import SearchVector, SearchVectorField
from django.core.serializers.json import DjangoJSONEncoder, json
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import transaction
from django.db.models import Q
from django.db.models.expressions import Value
from django.urls import reverse_lazy
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.utils.functional import cached_property
from private_storage.fields import PrivateFileField
from PIL import Image, ImageOps

from projects.actions import verbs
from projects.helpers import get_in_personnel_data, set_ad_data_in_attribute_data
from projects.models.utils import KaavapinoPrivateStorage, arithmetic_eval
from .attribute import Attribute, FieldSetAttribute
from .deadline import Deadline
from .projectcomment import FieldComment

log = logging.getLogger(__name__)


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
    metadata = models.JSONField(
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
    metadata = models.JSONField(
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

    def get_phases(self, project=None):
        if not project:
            return self.phases.all()

        phases = self.phases.all()
        if not project.create_principles:
            phases = phases.exclude(common_project_phase__name="Periaatteet")

        if not project.create_draft:
            phases = phases.exclude(common_project_phase__name="Luonnos")

        return phases


class ProjectPriority(models.Model):

    priority = models.PositiveIntegerField(
        verbose_name=_("priority"),
        default=1,
        unique=True,
        validators=[
            MinValueValidator(1),
            MaxValueValidator(10),
        ]
    )
    name = models.CharField(
        verbose_name=_("priority name"),
        max_length=64,
        unique=True,
        blank=False,
        null=False,
    )

    class Meta:
        verbose_name = _("project priority")
        verbose_name_plural = _("project priorities")
        ordering = ("-priority",)

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
    pino_number = models.CharField(
        max_length=7,
        verbose_name=_("pino number"),
        unique=True,
        blank=True,
        null=True,
    )
    subtype = models.ForeignKey(
        ProjectSubtype,
        verbose_name=_("subtype"),
        related_name="projects",
        on_delete=models.PROTECT,
    )
    priority = models.ForeignKey(
        ProjectPriority,
        verbose_name=_("project priority"),
        related_name="projects",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
    )
    attribute_data = models.JSONField(
        verbose_name=_("attribute data"),
        default=dict,
        blank=True,
        null=True,
        encoder=DjangoJSONEncoder,
    )
    deadlines = models.ManyToManyField(
        "ProjectDeadline",
        verbose_name=_("deadlines"),
        related_name="projects",
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
    archived_at = models.DateTimeField(
        verbose_name=_("archived at"),
        null=True,
        blank=True,
    )
    onhold = models.BooleanField(default=False)
    owner_edit_override = models.BooleanField(default=False)

    # For indexing
    vector_column = SearchVectorField(null=True)

    admin_description = "Voi muuttaa huoletta."

    class Meta:
        verbose_name = _("project")
        verbose_name_plural = _("projects")
        ordering = ("name",)
        indexes = (GinIndex(fields=["vector_column"]),)

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
                    deserialized_value = ProjectAttributeFile.objects.filter(
                        attribute=attribute, project=self
                    ).order_by("-created_at").first().file
                except AttributeError:
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

        for identifier, value in data.items():
            try:
                attribute = Attribute.objects.get(identifier=identifier)
            except Attribute.DoesNotExist:
                log.warning(f"Attribute {identifier} not found")
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
                    self.attribute_data.pop(identifier, None)
            elif attribute.value_type in [Attribute.TYPE_FIELDSET, Attribute.TYPE_INFO_FIELDSET]:
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

        return True

    # TODO disabled for now; frontend generates and sends values but we need to develop this later
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

    def _check_condition(self, deadline, preview_attributes={}):
        if not deadline.condition_attributes.count():
            return True

        attribute_data = {**self.attribute_data, **preview_attributes}
        for attr in deadline.condition_attributes.all():
            if bool(attribute_data.get(attr.identifier, None)):
                return True

        return False

    def get_applicable_deadlines(self, subtype=None, preview_attributes={}, initial=False):
        excluded_phases = []

        # TODO hard-coded, maybe change later
        if not self.create_principles:
            excluded_phases.append("Periaatteet")

        if not self.create_draft:
            excluded_phases.append("Luonnos")

        deadlines = Deadline.objects \
                .filter(subtype=subtype or self.subtype) \
                .exclude(phase__common_project_phase__name__in=excluded_phases) \
                .prefetch_related('condition_attributes') \
                .prefetch_related('initial_calculations') \
                .prefetch_related('update_calculations')

        return [
            deadline
            for deadline in deadlines
            if initial or self._check_condition(deadline, preview_attributes)
        ]

    def _set_calculated_deadline(self, deadline, date, user, preview, preview_attribute_data={}):
        try:
            if preview:
                try:
                    identifier = deadline.attribute.identifier
                except AttributeError:
                    identifier = None

                project_deadline = preview_attribute_data.get(identifier) or self.deadlines.get(deadline=deadline)
            else:
                project_deadline = ProjectDeadline.objects.get(project=self, deadline=deadline)
        except ProjectDeadline.DoesNotExist:
            return

        if project_deadline and date:
            if preview:
                return date

            project_deadline.date = date
            project_deadline.save()

            if deadline.attribute:
                old_value = json.loads(json.dumps(
                    self.attribute_data.get(deadline.attribute.identifier),
                    default=str,
                ))
                new_value = json.loads(json.dumps(date, default=str))

                self.update_attribute_data( \
                    {deadline.attribute.identifier: date})

                if old_value != new_value:
                    action.send(
                        user or self.user,
                        verb=verbs.UPDATED_ATTRIBUTE,
                        action_object=deadline.attribute,
                        target=self,
                        attribute_identifier=deadline.attribute.identifier,
                        old_value=old_value,
                        new_value=new_value,
                    )

            return date

    def _set_calculated_deadlines(self, deadlines, user, ignore=[], initial=False, preview=False, preview_attribute_data={}):
        results = {}
        fillers = []

        for deadline in deadlines:
            if initial:
                calculate_deadline = deadline.calculate_initial
                dependencies = [
                    dl for dl in deadline.initial_depends_on
                    if dl not in ignore
                ]
            else:
                calculate_deadline = deadline.calculate_updated
                dependencies = [
                    dl for dl in deadline.update_depends_on
                    if dl not in ignore
                ]

            if dependencies:
                ignore += dependencies
                results = { **results,
                    **self._set_calculated_deadlines(
                        dependencies,
                        user,
                        ignore=ignore,
                        initial=initial,
                        preview=preview,
                        preview_attribute_data=preview_attribute_data,
                    )
                }

            result = self._set_calculated_deadline(
                deadline,
                calculate_deadline(self, preview_attributes=preview_attribute_data),
                user,
                preview,
                preview_attribute_data,
            )

            if not result:
                fillers += [deadline]

            results[deadline] = result

        for deadline in fillers:
            # Another pass for few deadlines that depend on other deadlines
            if initial:
                calculate_deadline = deadline.calculate_initial
            else:
                calculate_deadline = deadline.calculate_updated

            self._set_calculated_deadline(
                deadline,
                calculate_deadline(self, preview_attributes=preview_attribute_data),
                user,
                preview,
                preview_attribute_data,
            )

        self.save()

        return results

    # Generate or update schedule for project
    def update_deadlines(self, user=None, initial=False):
        deadlines = self.get_applicable_deadlines(initial=initial)

        # Delete no longer relevant deadlines and create missing
        to_be_deleted = self.deadlines.exclude(deadline__in=deadlines)

        for dl in to_be_deleted:
            self.deadlines.remove(dl)

        generated_deadlines = []
        project_deadlines = list(self.deadlines.all())

        for deadline in deadlines:
            project_deadline, created = ProjectDeadline.objects.get_or_create(
                project=self,
                deadline=deadline,
                defaults={
                    "generated": True,
                }
            )
            if created:
                generated_deadlines.append(project_deadline)
                project_deadlines.append(project_deadline)

        self.deadlines.set(project_deadlines)

        # Update attribute-based deadlines
        for dl in self.deadlines.all().select_related("deadline__attribute"):
            if not dl.deadline.attribute:
                continue

            value = self.attribute_data.get(dl.deadline.attribute.identifier)
            value = value if value != 'null' else None
            dl.date = value
            dl.save()

        # Calculate automatic values for newly added deadlines
        self._set_calculated_deadlines(
            [
                dl.deadline for dl in generated_deadlines
                if dl.deadline.initial_calculations.count() \
                    or dl.deadline.default_to_created_at
            ],
            user,
            initial=True,
        )

        # Update automatic deadlines
        self._set_calculated_deadlines(
            [
                dl.deadline for dl in self.deadlines.all()
                if dl.deadline.update_calculations.count()
                   or dl.deadline.default_to_created_at
                   or dl.deadline.attribute
            ],
            user,
            initial=False,
        )

    # Calculate a preview schedule without saving anything
    def get_preview_deadlines(self, updated_attributes, subtype):
        # Filter out deadlines that would be deleted
        project_dls = {
            dl.deadline: dl.date
            for dl in self.deadlines.all()
            .select_related("deadline", "deadline__phase", "deadline__subtype", "deadline__attribute")
            .prefetch_related("deadline__initial_calculations", "deadline__update_calculations")
            if dl.deadline.subtype == subtype
        }

        # List deadlines that would be created
        new_dls = {
            dl: None
            for dl in self.get_applicable_deadlines(
                subtype=subtype,
                preview_attributes=updated_attributes,
            )
            if dl not in project_dls
        }

        project_dls = {**new_dls, **project_dls}

        # Update attribute-based deadlines
        updated_attribute_data = {**self.attribute_data, **updated_attributes}
        for dl in project_dls.keys():
            if not dl.attribute:
                continue

            value = updated_attribute_data.get(dl.attribute.identifier)

            if value:
                project_dls[dl] = value


        # Generate newly added deadlines
        project_dls = {**project_dls, **self._set_calculated_deadlines(
            [
                dl for dl in new_dls.keys()
                if dl.initial_calculations.count() or dl.default_to_created_at
            ],
            None,
            initial=True,
            preview=True,
        )}

        # Update all deadlines
        project_dls = {**project_dls, **self._set_calculated_deadlines(
            [
                dl for dl in project_dls
                if dl.update_calculations.count() \
                    or dl.default_to_created_at \
                    or dl.attribute
            ],
            None,
            initial=False,
            preview=True,
            preview_attribute_data=updated_attributes,
        )}

        return project_dls

    @property
    def type(self):
        return self.subtype.project_type

    @property
    def phase_documents_creation_started(self):
        # True if any documents in current phase has been downloaded at least once
        for template in \
            self.phase.common_project_phase.document_templates.filter(
                silent_downloads=False,
            ):
            if self.document_download_log.filter(
                document_template=template,
                phase=self.phase.common_project_phase,
            ).first():
                return True

        return False

    @property
    def phase_documents_created(self):
        # True if all documents in current phase have been downloaded at least once
        for template in \
            self.phase.common_project_phase.document_templates.filter(
                silent_downloads=False,
            ):
            if not self.document_download_log.filter(
                document_template=template,
                phase=self.phase.common_project_phase,
            ).first():
                return False

        return True

    def clear_data_by_data_retention_plan(self, data_retention_plan):
        updated = False
        for attribute in Attribute.objects.filter(data_retention_plan=data_retention_plan):
            current_value = self.attribute_data.get(attribute.identifier, None)
            if current_value:
                self.attribute_data[attribute.identifier] = None
                updated = True
        if updated:
            log.info(f"Clearing data by data_retention_plan '{data_retention_plan}' from project '{self}'")
            self.save()

    def clear_audit_log_data(self):
        log.info(f"Clearing audit log data from project '{self}'")
        LogEntry.objects.filter(object_id=str(self.pk)).delete()  # Clears django-admin logs from django_admin_log table
        ActStreamAction.objects.filter(target_object_id=str(self.pk)).delete()  # Clear audit logs from actstream_action table

    def save(self, *args, **kwargs):
        fieldset_attributes = {f for f in FieldSetAttribute.objects.all().select_related("attribute_source", "attribute_target")}

        def add_fieldset_field_for_attribute(search_fields, attr, fieldset, raw=False):
            key = attr.identifier
            while attr.fieldset_attribute_target.count():
                attr = next(filter(lambda a: a.attribute_target == attr, fieldset_attributes), None).attribute_source
                if not fieldset:
                    fieldset = self.attribute_data.get(attr.identifier)
                if not fieldset:
                    return

                for field in fieldset:
                    value = field.get(key)
                    # log.info('%s__%s: %s' % (attr.identifier, key, value))
                    if not value:
                        continue

                    if type(value) is list and attr.value_type in [Attribute.TYPE_FIELDSET, Attribute.TYPE_INFO_FIELDSET]:
                        sources = filter(lambda a: a.attribute_source.identifier == key, fieldset_attributes)
                        for source in sources:
                            add_fieldset_field_for_attribute(search_fields, source.attribute_target, value)
                    else:
                        if raw:
                            search_fields.add(Value(value, output_field=models.TextField()))
                        else:
                            search_fields.add(Value(check_get_name(value), output_field=models.TextField()))

        def add_search_field_for_attribute(search_fields, attr):
            if attr.static_property:
                value = getattr(self, attr.static_property, None)
                if value:
                    search_fields.add(Value(check_get_name(value), output_field=models.TextField()))
            elif not attr.fieldset_attribute_target.count():
                value = self.attribute_data.get(attr.identifier)
                if value and attr.value_type not in [Attribute.TYPE_FIELDSET, Attribute.TYPE_INFO_FIELDSET]:
                    search_fields.add(Value(check_get_name(value), output_field=models.TextField()))
            else:
                add_fieldset_field_for_attribute(search_fields, attr, None)

            return

        def check_get_name(value):
            if type(value) != str:
                return value

            from uuid import UUID

            try:
                _ = UUID(value, version=4)
            except ValueError:
                return value

            return get_in_personnel_data(value, 'name', False)

        # TODO: check if required
        # set_ad_data_in_attribute_data(self.attribute_data)
        search_fields = set()
        for attr in Attribute.objects.filter(searchable=True)\
                .prefetch_related("fieldsets", "fieldset_attribute_target", "fieldset_attribute_source"):
            add_search_field_for_attribute(search_fields, attr)

        # Raw personnels
        for attr in Attribute.objects.filter(value_type=Attribute.TYPE_PERSONNEL)\
                .prefetch_related("fieldsets", "fieldset_attribute_target", "fieldset_attribute_source"):
            if not attr.fieldset_attribute_target.count():
                value = self.attribute_data.get(attr.identifier)
                if value and attr.value_type not in [Attribute.TYPE_FIELDSET, Attribute.TYPE_INFO_FIELDSET]:
                    search_fields.add(Value(value, output_field=models.TextField()))
            else:
                add_fieldset_field_for_attribute(search_fields, attr, None, raw=True)

        search_fields.add(Value(self.subtype, output_field=models.TextField()))
        search_fields.add(Value(self.user, output_field=models.TextField()))
        search_fields.add(Value(self.user.ad_id, output_field=models.TextField()))

        self.vector_column = SearchVector(*list(search_fields))

        super(Project, self).save(*args, **kwargs)
        if not self.pino_number:
            self.pino_number = str(self.pk).zfill(7)
            self.save()


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

    class Meta:
        verbose_name = _("project floor area section attribute matrix structure")
        verbose_name_plural = _("project floor area section attribute matrix structures")


class ProjectFloorAreaSectionAttributeMatrixCell(BaseAttributeMatrixCell):
    attribute = models.ForeignKey(
        ProjectFloorAreaSectionAttribute, on_delete=models.CASCADE
    )
    structure = models.ForeignKey(
        ProjectFloorAreaSectionAttributeMatrixStructure, on_delete=models.CASCADE
    )

    def __str__(self):
        return f"{self.structure} {self.attribute} ({self.row}, {self.column})"


class CommonProjectPhase(models.Model):
    """Describes common, subtype-agnostic properties for a ProjectPhase."""

    name = models.CharField(max_length=255, verbose_name=_("name"))
    color = models.CharField(max_length=64, verbose_name=_("color"), blank=True)
    color_code = models.CharField(
        max_length=10, verbose_name=_("color code"), blank=True
    )
    list_prefix = models.CharField(
        max_length=2, verbose_name=_("list prefix"), blank=True, null=True
    )
    index = models.PositiveIntegerField(verbose_name=_("index"), default=0)

    class Meta:
        verbose_name = _("common project phase")
        verbose_name_plural = _("common project phases")
        ordering = ("index",)

    def __str__(self):
        return f"{self.name}"

    @property
    def subtypes(self):
        return ProjectSubtype.objects.filter(
            phases__in=self.phases.all(),
        )

    @property
    def prefixed_name(self):
        return f"{self.list_prefix}. {self.name}"


class ProjectPhase(models.Model):
    """Describes a phase of a certain project subtype."""

    common_project_phase = models.ForeignKey(
        CommonProjectPhase,
        verbose_name=_("common project phase"),
        on_delete=models.PROTECT,
        related_name="phases",
    )
    project_subtype = models.ForeignKey(
        ProjectSubtype,
        verbose_name=_("project subtype"),
        on_delete=models.CASCADE,
        related_name="phases",
    )
    index = models.PositiveIntegerField(verbose_name=_("index"), default=0)

    metadata = models.JSONField(
        verbose_name=_("metadata"),
        default=dict,
        blank=True,
        null=True,
        encoder=DjangoJSONEncoder,
    )

    admin_description = "Projektin vaiheet per kokoluokka, sekä niiden sisältö"

    class Meta:
        verbose_name = _("project phase")
        verbose_name_plural = _("project phases")
        ordering = ("index",)

    def __str__(self):
        return f"{self.common_project_phase} ({self.project_subtype.name})"

    @property
    def name(self):
        return self.common_project_phase.name

    @property
    def color(self):
        return self.common_project_phase.color

    @property
    def color_code(self):
        return self.common_project_phase.color_code

    @property
    def list_prefix(self):
        return self.common_project_phase.list_prefix

    @property
    def project_type(self):
        return self.project_subtype.project_type

    @property
    def prefixed_name(self):
        return self.common_project_phase.prefixed_name


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
    ingress = models.CharField(max_length=255, verbose_name=_("ingress"), default="")
    index = models.PositiveIntegerField(verbose_name=_("index"), default=0)
    attributes = models.ManyToManyField(
        Attribute,
        verbose_name=_("attributes"),
        related_name="phase_sections",
        through="ProjectPhaseSectionAttribute",
    )

    admin_description = "Kentät projektivaiheissa"


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


PROJECT_CARD_SECTION_KEYS = (
    ("projektikortin_kuva", "projektikortin_kuva"),
    ("perustiedot", "perustiedot"),
    ("suunnittelualueen_kuvaus", "suunnittelualueen_kuvaus"),
    ("strategiakytkenta", "strategiakytkenta"),
    ("maanomistus", "maanomistus"),
    ("kerrosalatiedot", "kerrosalatiedot"),
    ("aikataulu", "aikataulu"),
    ("yhteyshenkilöt", "yhteyshenkilöt"),
    ("dokumentit", "dokumentit"),
    ("suunnittelualueen_rajaus", "suunnittelualueen_rajaus"),
)


class ProjectCardSection(models.Model):
    """Defines a section to be shown on project card view."""

    name = models.CharField(
        max_length=255,
        verbose_name=_("name"),
    )
    index = models.PositiveIntegerField(
        verbose_name=_("index"),
        default=0,
    )

    key = models.CharField(
        choices=PROJECT_CARD_SECTION_KEYS,
        max_length=255,
        verbose_name=_("key"),
        null=True,
    )

    admin_description = "Ei vielä tuettu käyttöliittymässä"

    class Meta:
        verbose_name = _("project card section")
        verbose_name_plural = _("project card sections")
        ordering = ("index",)

    def __str__(self):
        return f"{self.name}"

class ProjectCardSectionAttribute(models.Model):
    """Links an attribute into a project card section."""
    attribute = models.ForeignKey(
        Attribute,
        verbose_name=_("attribute"),
        on_delete=models.CASCADE,
    )
    section = models.ForeignKey(
        ProjectCardSection,
        verbose_name=_("project card section"),
        related_name="attributes",
        on_delete=models.CASCADE,
    )
    custom_label = models.CharField(
        max_length=255,
        verbose_name=_("custom label"),
        null=True,
        blank=True,
    )
    date_format = models.CharField(
        max_length=255,
        verbose_name=_("date format and text"),
        null=True,
        blank=True,
    )
    index = models.PositiveIntegerField(
        verbose_name=_("index"),
        default=0,
    )
    show_on_mobile = models.BooleanField(
        verbose_name=_("show on mobile"),
        default=True,
    )

    class Meta:
        verbose_name = _("project card section attribute")
        verbose_name_plural = _("project card section attributes")
        ordering = ("index",)

    def __str__(self):
        return f"{self.attribute} {self.section} {self.index}"


class ProjectPhaseFieldSetAttributeIndex(models.Model):
    index = models.PositiveIntegerField(verbose_name=_("index"), default=0)
    phase = models.ForeignKey(
        ProjectPhase, on_delete=models.CASCADE
    )
    attribute = models.ForeignKey(
        FieldSetAttribute, on_delete=models.CASCADE
    )
    unique_together = ("attribute", "phase")

    def __str__(self):
        return f"{self.attribute} {self.phase} {self.index}"


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
    created_at = models.DateTimeField(
        verbose_name=_("created at"),auto_now_add=True, editable=False
    )
    archived_at = models.DateTimeField(
        verbose_name=_("archived at"),
        null=True,
        blank=True,
    )
    fieldset_path_str = models.TextField(
        verbose_name=_("fieldset path string"),
        null=True,
        blank=True,
    )

    @cached_property
    def fieldset_path(self):
        return [
            {"parent": loc.parent_fieldset, "index": loc.child_index}
            for loc in self.fieldset_path_locations.all()
        ]

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

    def save(self, *args, **kwargs):
        super(ProjectAttributeFile, self).save(*args, **kwargs)
        # portrait a4 paper @ 200dpi
        paper_size_in_pixels = (1654, 2339)
        try:
            # resize to 200dpi print size
            image = Image.open(self.file.path)
            image = ImageOps.exif_transpose(image)
            exif = image.getexif()
            image.thumbnail(paper_size_in_pixels, Image.Resampling.LANCZOS)
            if image.format == 'JPEG':
                image.save(self.file.path, quality=100, optimize=True, exif=exif)
            else:
                image.save(self.file.path, optimize=True, exif=exif)
        except IOError:
            # not an image
            pass

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

    class Meta:
        verbose_name = _("phase attribute matrix structure")
        verbose_name_plural = _("phase attribute matrix structure")


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


class ProjectDeadline(models.Model):
    deadline = models.ForeignKey(
        Deadline,
        verbose_name=_("deadline"),
        related_name="project_deadlines",
        on_delete=models.CASCADE,
    )
    project = models.ForeignKey(
        Project,
        verbose_name=_("project"),
        related_name="project_deadlines",
        on_delete=models.CASCADE,
    )
    date = models.DateField(
        verbose_name=_("deadline date"),
        null=True,
        blank=True,
    )
    generated = models.BooleanField(
        verbose_name=_("generated"),
        default=False,
    )
    edited = models.DateTimeField(
        verbose_name=_("modified at"),
        editable=False,
        null=True,
        blank=True,
    )

    @property
    def confirmed(self):
        try:
            identifier = self.deadline.confirmation_attribute.identifier
        except AttributeError:
            return None

        value = self.project.attribute_data.get(identifier)

        if value is not None:
            return bool(value)

        return None

    class Meta:
        unique_together = ("deadline", "project")
        ordering = ("deadline__index",)

    def __str__(self):
        return f"{self.deadline.abbreviation} {self.date}"


class ProjectPhaseDeadlineSectionAttribute(models.Model):
    """Links an attribute into a project phase deadline section."""

    attribute = models.ForeignKey(
        Attribute,
        verbose_name=_("attribute"),
        on_delete=models.CASCADE,
    )
    section = models.ForeignKey(
        "ProjectPhaseDeadlineSection",
        verbose_name=_("deadline phase section"),
        on_delete=models.CASCADE,
    )
    owner_field = models.BooleanField(
        default=False,
        verbose_name=_("show for project owner"),
    )
    admin_field = models.BooleanField(
        default=False,
        verbose_name=_("show for administrator"),
    )
    index = models.PositiveIntegerField(verbose_name=_("index"), default=0)

    class Meta:
        verbose_name = _("project phase deadline section item")
        verbose_name_plural = _("project phase deadline section items")
        ordering = ("index",)

    def __str__(self):
        return f"{self.attribute} {self.section} {self.index}"


class ProjectPhaseDeadlineSection(models.Model):
    """Defines a deadline section for a project phase."""

    phase = models.ForeignKey(
        ProjectPhase,
        verbose_name=_("phase"),
        related_name="deadline_sections",
        on_delete=models.CASCADE,
    )
    index = models.PositiveIntegerField(verbose_name=_("index"), default=0)
    attributes = models.ManyToManyField(
        Attribute,
        verbose_name=_("attributes"),
        related_name="phase_deadline_sections",
        through="ProjectPhaseDeadlineSectionAttribute",
    )

    admin_description = "Aikataulumodaalin osiot ja kentät"

    @property
    def name(self):
        return f"{self.phase.list_prefix}. {self.phase.name}"

    class Meta:
        verbose_name = _("project phase deadline section")
        verbose_name_plural = _("project phase deadline sections")
        ordering = ("index",)

    def __str__(self):
        return f"{self.phase.name}, {self.phase.project_subtype.name}"


class FieldsetPathLocation(models.Model):
    """Defines a single node in a fieldset path to a field"""
    child_index = models.PositiveIntegerField(verbose_name=_("child index"))
    parent_fieldset = models.ForeignKey(
        Attribute,
        verbose_name=_("parent fieldset"),
        on_delete=models.CASCADE,
    )
    index = models.PositiveIntegerField(verbose_name=_("index"))

    class Meta:
        abstract = True
        ordering = ("index",)


class ProjectAttributeFileFieldsetPathLocation(FieldsetPathLocation):
    target = models.ForeignKey(
        ProjectAttributeFile,
        verbose_name=_("target file"),
        related_name="fieldset_path_locations",
        on_delete=models.CASCADE,
    )

    class Meta(FieldsetPathLocation.Meta):
        unique_together = ("index", "target")


class FieldCommentFieldsetPathLocation(FieldsetPathLocation):
    target = models.ForeignKey(
        FieldComment,
        verbose_name=_("target comment"),
        related_name="fieldset_path_locations",
        on_delete=models.CASCADE,
    )

    class Meta(FieldsetPathLocation.Meta):
        unique_together = ("index", "target")
