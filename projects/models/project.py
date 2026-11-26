import datetime
import itertools
import logging
import time

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
from django.db.models.expressions import Value
from django.urls import reverse_lazy
from django.utils.text import slugify
from django.utils.translation import gettext_lazy as _
from django.utils.functional import cached_property
from private_storage.fields import PrivateFileField
from PIL import Image, ImageOps

from projects.actions import verbs
from projects.helpers import get_in_personnel_data
from projects.models.utils import KaavapinoPrivateStorage, arithmetic_eval
from projects.serializers.utils import get_dl_vis_bool_name
from .attribute import Attribute, FieldSetAttribute
from .deadline import Deadline
from .projectcomment import FieldComment

from projects.serializers.utils import VIS_BOOL_MAP

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
    onhold_at = models.DateTimeField(
        verbose_name=_("onhold at"),
        null=True,
        blank=True,
    )
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

    def update_attribute_data(self, data, confirmed_fields=None, fake=False, attribute_cache=None):
        confirmed_fields = confirmed_fields or []
        attribute_cache = attribute_cache or {}

        if not isinstance(self.attribute_data, dict):
            self.attribute_data = {}

        if not data:
            return False

        identifiers_to_fetch = [
            identifier
            for identifier in data.keys()
            if isinstance(identifier, str) and identifier not in attribute_cache
        ]
        if identifiers_to_fetch:
            fetched_attributes = Attribute.objects.filter(
                identifier__in=identifiers_to_fetch
            ).prefetch_related("value_choices")
            attribute_cache.update({attr.identifier: attr for attr in fetched_attributes})

        for identifier, value in data.items():
            attribute = attribute_cache.get(identifier)
            if not attribute:
                log.warning(f"Attribute {identifier} not found")
                continue

            self.attribute_data[identifier] = value
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

            if attribute_data.get(attribute.identifier, None) is None:
                attribute_data[attribute.identifier] = calculated_value

    def _check_condition(self, deadline, preview_attributes={}):
        if not deadline.condition_attributes.exists():
            return True

        attribute_data = {**self.attribute_data, **preview_attributes}
        for attr in deadline.condition_attributes.all():
            if bool(attribute_data.get(attr.identifier, None)):
                return True

        return False

    def get_applicable_deadlines(self, subtype=None, preview_attributes={}, initial=False, for_record_existence=False):
        """Get deadlines applicable to this project.
        
        Args:
            subtype: Override project subtype
            preview_attributes: Attributes for preview calculation
            initial: If True, include all deadlines (initial project creation)
            for_record_existence: If True, return ALL deadlines for subtype, ignoring
                condition_attributes. Used by update_deadlines() to ensure ProjectDeadline
                records are never deleted just because a visibility bool is False.
                Per docs: E2.2 must ALWAYS exist so it can appear when vis_bool becomes True.
        """
        excluded_phases = []

        # TODO hard-coded, maybe change later
        if not self.create_principles:
            excluded_phases.append("Periaatteet")

        if not self.create_draft:
            excluded_phases.append("Luonnos")

        deadlines = Deadline.objects \
                .filter(subtype=subtype or self.subtype) \
                .exclude(phase__common_project_phase__name__in=excluded_phases) \
                .select_related('phase', 'subtype', 'attribute', 'phase__project_subtype', 'phase__common_project_phase', ) \
                .prefetch_related('condition_attributes') \
                .prefetch_related('initial_calculations') \
                .prefetch_related('update_calculations') \

        # for_record_existence=True: return ALL deadlines (for creating/keeping ProjectDeadline records)
        # initial=True: same behavior (initial project creation)
        # Otherwise: filter by condition_attributes (for visibility/calculation checks)
        if for_record_existence or initial:
            return list(deadlines)
        
        return [
            deadline
            for deadline in deadlines
            if self._check_condition(deadline, preview_attributes)
        ]

    def is_deadline_applicable(self, deadline, preview_attributes={}):
        if deadline.subtype != self.subtype:
            return False
        elif deadline.phase.name == "Periaatteet" and not self.create_principles:
            return False
        elif deadline.phase.name == "Luonnos" and not self.create_draft:
            return False
        return self._check_condition(deadline, preview_attributes)

    def _coerce_date_value(self, value):
        if value is None:
            return None
        if isinstance(value, datetime.datetime):
            return value.date()
        if isinstance(value, datetime.date):
            return value
        if isinstance(value, str):
            try:
                return datetime.date.fromisoformat(value)
            except ValueError:
                try:
                    return datetime.datetime.strptime(value, "%Y-%m-%d").date()
                except ValueError:
                    return None
        return None

    def _resolve_deadline_date(self, deadline, preview_attribute_data=None):
        if not deadline:
            return None

        identifier = getattr(getattr(deadline, "attribute", None), "identifier", None)
        if identifier and preview_attribute_data and identifier in preview_attribute_data:
            val = preview_attribute_data[identifier]
            return self._coerce_date_value(val)

        if identifier:
            attr_value = self.attribute_data.get(identifier)
            coerced_value = self._coerce_date_value(attr_value)
            if coerced_value:
                return coerced_value

        try:
            dl_date = self.deadlines.get(deadline=deadline).date
            return dl_date
        except ProjectDeadline.DoesNotExist:
            return None

    def _min_distance_target_date(self, prev_date, distance, deadline):
        if not prev_date:
            return None

        if distance.date_type:
            min_candidate = distance.date_type.valid_days_from(
                prev_date,
                distance.distance_from_previous,
            )
        else:
            min_candidate = prev_date + datetime.timedelta(days=distance.distance_from_previous)

        if not min_candidate:
            return None

        if deadline.date_type:
            return deadline.date_type.get_closest_valid_date(min_candidate)
        return min_candidate

    def _enforce_distance_requirements(self, deadline, date, preview_attribute_data=None):
        current_date = self._coerce_date_value(date)
        if not current_date:
            return date

        combined_attributes = dict(self.attribute_data or {})
        if preview_attribute_data:
            combined_attributes.update(preview_attribute_data)

        for distance in deadline.distances_to_previous.all():
            conditions_ok = distance.check_conditions(combined_attributes)
            if not conditions_ok:
                continue

            prev_date = self._resolve_deadline_date(distance.previous_deadline, preview_attribute_data)
            prev_date = self._coerce_date_value(prev_date)
            if not prev_date:
                continue

            min_target = self._min_distance_target_date(prev_date, distance, deadline)
            
            if not min_target:
                continue

            if current_date < min_target:
                current_date = min_target

        # Snap to the deadline's date_type if one exists
        if deadline.date_type and current_date:
            valid_date = deadline.date_type.get_closest_valid_date(current_date)
            if valid_date and valid_date != current_date:
                current_date = valid_date

        identifier = getattr(getattr(deadline, "attribute", None), "identifier", None)
        if preview_attribute_data is not None and identifier and current_date:
            preview_attribute_data[identifier] = current_date
        
        return current_date

    def _set_calculated_deadline(self, deadline, date, user, preview, preview_attribute_data=None, confirmed_fields=None):
        if preview_attribute_data is None:
            preview_attribute_data = {}
        if confirmed_fields is None:
            confirmed_fields = {}

        if not date:
            return None

        try:
            if preview:
                try:
                    identifier = deadline.attribute.identifier
                except AttributeError:
                    identifier = None

                project_deadline = preview_attribute_data.get(identifier) or self.deadlines.filter(deadline=deadline).exists()
            else:
                project_deadline = ProjectDeadline.objects.get(project=self, deadline=deadline)
        except ProjectDeadline.DoesNotExist:
            return None

        if project_deadline:
            if deadline.attribute and deadline.attribute.identifier:
                # Check if the attribute is in confirmed_fields - if so, keep the original value
                identifier = deadline.attribute.identifier
                # Check if the attribute is in confirmed_fields - if so, keep the original value
                identifier = deadline.attribute.identifier
                if identifier in confirmed_fields:
                    # Confirmed fields: prefer request value (may be fresher than DB)
                    if preview and preview_attribute_data and identifier in preview_attribute_data:
                        val = preview_attribute_data.get(identifier)
                        return val
                    
                    val = self.attribute_data.get(identifier)
                    return val

                # Auto-calculated fields (edit_privilege=None) always recalculate.
                # User-editable fields use preview value to avoid overwriting user input.
                is_auto_calculated = deadline.edit_privilege is None
                if preview and preview_attribute_data and identifier in preview_attribute_data and not is_auto_calculated:
                    preview_val = preview_attribute_data.get(identifier)
                    if preview_val is not None:
                        # Use the preview value, enforce it, and return
                        enforced_date = self._enforce_distance_requirements(
                            deadline,
                            preview_val,
                            preview_attribute_data,
                        )
                        return enforced_date

            enforced_date = self._enforce_distance_requirements(
                deadline,
                date,
                preview_attribute_data if preview else None,
            )

            if preview:
                return enforced_date

            if not project_deadline.editable:
                return None

            if project_deadline.date != enforced_date:
                project_deadline.date = enforced_date
                project_deadline.save()

            if deadline.attribute:
                # DEADLINE_INTEGRITY_RULES: Dates must ALWAYS exist in attribute_data
                # for cascade calculation. Visibility bool controls UI display only,
                # not data existence. Never skip writing dates based on vis_bool.
                old_value = json.loads(json.dumps(
                    self.attribute_data.get(deadline.attribute.identifier),
                    default=str,
                ))
                new_value = json.loads(json.dumps(enforced_date, default=str))

                self.update_attribute_data(
                    {deadline.attribute.identifier: enforced_date},
                    attribute_cache={
                        deadline.attribute.identifier: deadline.attribute
                    },
                )

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
            return enforced_date

        return None

    def _set_calculated_deadlines(self, deadlines, user, ignore=None, initial=False, preview=False, preview_attribute_data=None, is_recursing=False, confirmed_fields=None, calculation_cache=None, timing_metrics=None, user_changed_fields=None):
        if preview_attribute_data is None:
            preview_attribute_data = {}
        if confirmed_fields is None:
            confirmed_fields = {}
        if ignore is None:
            ignore = []
        if user_changed_fields is None:
            user_changed_fields = set()
        calc_start = time.monotonic() if timing_metrics is not None else None
        results = {}
        fillers = []
        
        def _cache_key_for(deadline_obj):
            if not (preview and calculation_cache is not None):
                return None
            preview_scope = id(preview_attribute_data) if preview_attribute_data else 0
            return (deadline_obj.pk, initial, preview_scope)

        def _process_deadline(deadline_obj, calculate_deadline_fn):
            cache_key = _cache_key_for(deadline_obj)
            if cache_key and cache_key in calculation_cache:
                cached_value = calculation_cache[cache_key]
                if cached_value is not None:
                    return cached_value

            # User-changed deadlines: enforce distances only, don't recalculate.
            # Auto-calculated deadlines (phase boundaries): always recalculate.
            identifier = deadline_obj.attribute.identifier if deadline_obj.attribute else None
            is_auto_calculated = deadline_obj.edit_privilege is None
            if identifier and identifier in user_changed_fields and not is_auto_calculated:
                user_value = preview_attribute_data.get(identifier)
                if user_value is not None:
                    enforced = self._enforce_distance_requirements(
                        deadline_obj,
                        user_value,
                        preview_attribute_data,
                    )
                    if cache_key and enforced is not None:
                        calculation_cache[cache_key] = enforced
                    return enforced

            computed_date = calculate_deadline_fn(self, preview_attributes=preview_attribute_data)
            
            result = self._set_calculated_deadline(
                deadline_obj,
                computed_date,
                user,
                preview,
                preview_attribute_data,
                confirmed_fields=confirmed_fields,
            )

            if cache_key and result is not None:
                calculation_cache[cache_key] = result

            return result

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
                        is_recursing=True,
                        confirmed_fields=confirmed_fields,
                        calculation_cache=calculation_cache,
                        timing_metrics=timing_metrics,
                        user_changed_fields=user_changed_fields,
                    )
                }

            result = _process_deadline(deadline, calculate_deadline)
            if not result:
                fillers += [deadline]

            results[deadline] = result

        for deadline in fillers:
            # Another pass for few deadlines that depend on other deadlines
            if initial:
                calculate_deadline = deadline.calculate_initial
            else:
                calculate_deadline = deadline.calculate_updated

            _process_deadline(deadline, calculate_deadline)

        if not is_recursing and not preview:
            self.save()

        if calc_start is not None:
            elapsed = time.monotonic() - calc_start
            timing_metrics["deadline_calc"] = timing_metrics.get("deadline_calc", 0.0) + elapsed

        return results

    # Generate or update schedule for project
    def update_deadlines(self, user=None, initial=False, preview_attributes={}, confirmed_fields={}, timing_metrics=None, timeline_save=False, old_subtype=None):
        # CRITICAL: Use for_record_existence=True to get ALL deadlines for this subtype.
        # This ensures ProjectDeadline records are NEVER deleted just because a visibility
        # bool (condition_attribute) is False. Per docs/database_deadline_rules.md and
        # docs/validation.md: E2.2 must ALWAYS exist so it can appear when nähtävilläolo-2
        # is enabled. Deleting records would break the "add back" functionality.
        deadlines = self.get_applicable_deadlines(for_record_existence=True, preview_attributes=preview_attributes)

        # Delete only deadlines that are truly inapplicable (wrong subtype or excluded phase)
        # NOT deadlines that are just hidden due to condition_attributes (vis_bool=False)
        to_be_deleted = self.deadlines.exclude(deadline__in=deadlines)

        for dl in to_be_deleted:
            self.deadlines.remove(dl)
            dl.delete()
            # Remove from attribute data if the dl is not applicable to the new subtype
            if dl.deadline.attribute and dl.deadline.attribute.identifier in self.attribute_data:
                if not dl.deadline.attribute.identifier in [deadline.attribute.identifier for deadline in deadlines if deadline.attribute]:
                    self.attribute_data.pop(dl.deadline.attribute.identifier)

        generated_deadlines = []
        project_deadlines = list(ProjectDeadline.objects.filter(project=self, deadline__in=deadlines)
                                 .select_related("deadline"))
        existing_dls = [p_dl.deadline for p_dl in project_deadlines]

        for deadline in deadlines:
            if not deadline in existing_dls:
                new_project_deadline = ProjectDeadline.objects.create(
                    project=self,
                    deadline=deadline,
                    generated=True
                )
                if deadline.deadlinegroup:
                    vis_bool = get_dl_vis_bool_name(deadline.deadlinegroup)
                    if vis_bool and not vis_bool in self.attribute_data:
                        self.attribute_data[vis_bool] = True if deadline.deadlinegroup.endswith('1') else False
                generated_deadlines.append(new_project_deadline)
                project_deadlines.append(new_project_deadline)
        self.deadlines.set(project_deadlines)

        if old_subtype:  # Subtype changed, update visibility booleans for deadlines that have changed
            old_subtype_deadlines = {dl.abbreviation: dl for dl in self.get_applicable_deadlines(subtype=old_subtype)}
            new_subtype_deadlines = {dl.abbreviation: dl for dl in self.get_applicable_deadlines(subtype=self.subtype)}
            for abbreviation, dl in new_subtype_deadlines.items():
                if abbreviation not in old_subtype_deadlines.keys():
                    # Set visibility booleans to True
                    if dl.deadlinegroup:
                        vis_bool = get_dl_vis_bool_name(dl.deadlinegroup)
                        if vis_bool:
                            self.attribute_data[vis_bool] = True if dl.deadlinegroup.endswith('1') else False
            for abbreviation, dl in old_subtype_deadlines.items():
                if abbreviation not in new_subtype_deadlines.keys():
                    # Set visibility booleans to False
                    if dl.deadlinegroup:
                        vis_bool = get_dl_vis_bool_name(dl.deadlinegroup)
                        if vis_bool:
                            self.attribute_data[vis_bool] = False

        # K1 = U1 sync: kaynnistysvaihe_alkaa_pvm always equals projektin_kaynnistys_pvm
        # Per timeline_requirements.md line 899: K1's "Generoitu ehdotus" = U1
        if self.attribute_data.get('projektin_kaynnistys_pvm'):
            u1_value = self.attribute_data['projektin_kaynnistys_pvm']
            self.attribute_data['kaynnistysvaihe_alkaa_pvm'] = u1_value
            # Directly update K1's ProjectDeadline record (bypasses for loop that may skip it)
            ProjectDeadline.objects.filter(
                project=self,
                deadline__abbreviation='K1'
            ).update(date=u1_value)

        # Update attribute-based deadlines
        dls_to_update = []
        for dl in self.deadlines.all().select_related("deadline__attribute"):
            if not dl.deadline.attribute:
                continue

            value = self.attribute_data.get(dl.deadline.attribute.identifier)
            value = value if value != 'null' else None
            if dl.date != value:
                dl.date = value
                dls_to_update.append(dl)
        self.deadlines.bulk_update(dls_to_update, ['date'])
        
        # Calculate initial values for newly added deadlines
        # BUT: Per docs/validation.md - during timeline_save, NO RECALCULATION.
        # The frontend already received calculated dates from preview and is sending them.
        # We just sync the values AS-IS without recalculating.
        if generated_deadlines and not timeline_save:
            self._set_calculated_deadlines(
                [
                    dl.deadline for dl in generated_deadlines
                    if dl.deadline.initial_calculations.exists() \
                        or dl.deadline.default_to_created_at
                ],
                user,
                initial=True,
                preview_attribute_data=preview_attributes,
                confirmed_fields=confirmed_fields,
                timing_metrics=timing_metrics,
            )

        # Per docs/validation.md: During save (fake=false), NO RECALCULATION.
        # Validation already happened in get_deadline_validator().
        # Lines above synced frontend values to ProjectDeadline.date AS-IS.
        # Save the project to persist the changes.
        self.save()

    # Calculate a preview schedule without saving anything
    def get_raw_deadline_preview(self, updated_attributes, subtype):
        """
        Build a preview dict with RAW request values - no cascade, no enforcement.
        Used for timeline_save validation where we want to validate user's exact input.
        
        Returns dict with:
        - Deadline objects as keys
        - Raw date values from request (or DB for unchanged deadlines)
        - String keys for visibility booleans
        """
        project_dls = {}
        for dl in self.deadlines.filter(deadline__subtype=subtype) \
            .select_related("deadline", "deadline__attribute"):
            deadline = dl.deadline
            # Use updated value from request if available, otherwise use database value
            if deadline.attribute and deadline.attribute.identifier in updated_attributes:
                project_dls[deadline] = updated_attributes[deadline.attribute.identifier]
            else:
                project_dls[deadline] = dl.date
        
        # Include visibility booleans and other attribute data
        combined = {**self.attribute_data, **updated_attributes}
        for key, value in combined.items():
            if isinstance(key, str):
                project_dls[key] = value
        
        return project_dls


    def get_preview_deadlines(self, updated_attributes, subtype, confirmed_fields=None, locked_group=None):
        confirmed_fields = set(confirmed_fields or [])
        preview_data = {**self.attribute_data, **updated_attributes}

        # 1-2. Fetch project deadlines for the given subtype, sorted by index.
        project_deadlines = list(
            self.deadlines.filter(deadline__subtype=subtype).select_related(
                "deadline",
                "deadline__attribute",
                "deadline__date_type",
                "deadline__confirmation_attribute",
            ).prefetch_related(
                "deadline__distances_to_previous",
                "deadline__update_calculations",
            )
        )
        dl_to_pdl = {pdl.deadline: pdl for pdl in project_deadlines}
        deadlines = sorted(dl_to_pdl.keys(), key=lambda d: d.index)

        # 3. Track identifiers whose stored value differs from the request.
        changed_ids = {
            identifier
            for identifier, new_value in updated_attributes.items()
            if self._coerce_date_value(self.attribute_data.get(identifier))
            != self._coerce_date_value(new_value)
        }

        # Seed the result with request values, falling back to the stored date.
        result = {}
        for dl, pdl in dl_to_pdl.items():
            identifier = dl.attribute.identifier if dl.attribute else None
            if identifier and identifier in updated_attributes:
                result[dl] = updated_attributes[identifier]
            else:
                result[dl] = pdl.date

        # 4. Find the first (by index) changed deadline.
        first_idx = next(
            (i for i, dl in enumerate(deadlines)
             if dl.attribute and dl.attribute.identifier in changed_ids),
            None,
        )

        # 5. Walk forward from the first changed deadline.
        if first_idx is not None:
            for dl in deadlines[first_idx:]:
                if not dl.attribute:
                    continue
                identifier = dl.attribute.identifier

                # a. Skip confirmed deadlines.
                if identifier in confirmed_fields:
                    continue
                conf_attr = dl.confirmation_attribute
                if conf_attr and preview_data.get(conf_attr.identifier):
                    continue

                # b/c. Recalculate when update_calculations depend on a changed DL.
                recalculated = False
                new_date = None
                if dl.update_calculations.exists():
                    depends_on_changed = any(
                        dep.attribute and dep.attribute.identifier in changed_ids
                        for dep in dl.update_depends_on
                    )
                    if depends_on_changed:
                        new_date = self._coerce_date_value(
                            dl.calculate_updated(self, preview_attributes=preview_data)
                        )
                        recalculated = True

                # d. Otherwise enforce minimum distance (no-op if already valid).
                if not recalculated:
                    current = result.get(dl)
                    if current is None:
                        continue
                    new_date = self._enforce_distance_requirements(
                        dl, current, preview_attribute_data=preview_data
                    )
    
                if new_date and new_date != self._coerce_date_value(result.get(dl)):
                    if locked_group and locked_group == dl.deadlinegroup:
                        raise ValueError(f"Change prevented due to '{locked_group}' being locked.")
                    result[dl] = new_date
                    preview_data[identifier] = new_date
                    changed_ids.add(identifier)

        # Pass visibility booleans through unchanged.
        for key, value in preview_data.items():
            if isinstance(value, bool):
                result[key] = value

        return result


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
            self.save()

    def clear_audit_log_data(self):
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

        # Normalize search_fields
        normalized_search_fields = set()
        for search_field in search_fields:
            normalized_value = (str(search_field).lower()
                                .replace(" ", "")
                                .replace("-", "")
                                .replace("_", "")
                                .replace(".", "")
                                )
            normalized_search_fields.add(Value(normalized_value, output_field=models.TextField()))

        self.vector_column = SearchVector(*list(normalized_search_fields))

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
            image_format = image.format # deleted from image data during transpose
            image = ImageOps.exif_transpose(image)
            image.thumbnail(paper_size_in_pixels, Image.Resampling.LANCZOS)
            if image_format == 'JPEG':
                image.save(self.file.path, quality=100, optimize=True)
            else:
                image.save(self.file.path, optimize=True)
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
    editable = models.BooleanField(
        verbose_name=_("editable"),
        default=True,
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


class EmailTemplate(models.Model):
    """Email templates that are used when sending certain types of emails.
    """

    name = models.CharField(max_length=255, verbose_name=_("name"), unique=True)
    slug = models.SlugField(editable=False, max_length=255)

    def get_upload_subfolder(self):
        return ["email_templates", self.slug]

    file = PrivateFileField(
        "File",
        storage=KaavapinoPrivateStorage(
            base_url=reverse_lazy(
                "serve_private_email_template_file", kwargs={"path": ""}
            ),
            url_postfix="email_templates",
        ),
        upload_subfolder=get_upload_subfolder,
        max_length=255,
    )

    admin_description = "Sähköpostipohjien hallintaa"

    class Meta:
        verbose_name = _("email template")
        verbose_name_plural = _("email templates")

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        return super().save(*args, **kwargs)


class EmailMessage(models.Model):
    """EmailMessage represents an email message that can be sent or scheduled for later.
    """
    recipient = models.CharField(max_length=255, verbose_name=_("recipient"))
    subject = models.TextField(verbose_name=_("subject"))
    message = models.TextField(verbose_name=_("message"))
    template = models.ForeignKey(
        EmailTemplate,
        verbose_name=_("template"),
        related_name="messages",
        on_delete=models.CASCADE,
        blank=True,
        null=True,
    )
    context = models.JSONField(verbose_name=_("context"), blank=True, null=True, default=dict)
    scheduled_time = models.DateTimeField(verbose_name=_("scheduled time"), null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, editable=False)


# Register auditlog for models
from auditlog.registry import auditlog
#auditlog.register(BaseAttributeMatrixStructure)
#auditlog.register(BaseAttributeMatrixCell)
auditlog.register(ProjectType)
auditlog.register(ProjectSubtype)
auditlog.register(ProjectPriority)
auditlog.register(Project, exclude_fields=["vector_column"])
auditlog.register(ProjectFloorAreaSection)
auditlog.register(ProjectFloorAreaSectionAttribute)
#auditlog.register(ProjectFloorAreaSectionAttributeMatrixStructure)
#auditlog.register(ProjectFloorAreaSectionAttributeMatrixCell)
auditlog.register(CommonProjectPhase)
auditlog.register(ProjectPhase)
#auditlog.register(ProjectPhaseLog)
auditlog.register(ProjectPhaseSection)
auditlog.register(ProjectPhaseSectionAttribute)
auditlog.register(ProjectCardSection)
auditlog.register(ProjectPhaseFieldSetAttributeIndex)
auditlog.register(ProjectAttributeFile)
#auditlog.register(PhaseAttributeMatrixStructure)
#auditlog.register(PhaseAttributeMatrixCell)
#auditlog.register(ProjectAttributeMultipolygonGeometry)
#auditlog.register(ProjectDeadline)
auditlog.register(ProjectPhaseDeadlineSectionAttribute)
auditlog.register(ProjectPhaseDeadlineSection)
auditlog.register(FieldsetPathLocation)
auditlog.register(ProjectAttributeFileFieldsetPathLocation)
auditlog.register(FieldCommentFieldsetPathLocation)
auditlog.register(EmailTemplate)
