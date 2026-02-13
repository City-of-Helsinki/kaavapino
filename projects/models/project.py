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
            log.warning("[DEBUG RESOLVE] '%s' from preview_attribute_data = %s", identifier, val)
            return self._coerce_date_value(val)

        if identifier:
            attr_value = self.attribute_data.get(identifier)
            coerced_value = self._coerce_date_value(attr_value)
            if coerced_value:
                log.warning("[DEBUG RESOLVE] '%s' from self.attribute_data = %s", identifier, coerced_value)
                return coerced_value

        try:
            dl_date = self.deadlines.get(deadline=deadline).date
            log.warning("[DEBUG RESOLVE] '%s' from ProjectDeadline = %s", identifier, dl_date)
            return dl_date
        except ProjectDeadline.DoesNotExist:
            log.warning("[DEBUG RESOLVE] '%s' NOT FOUND in any source", identifier)
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

            if preview or not project_deadline.editable:
                return enforced_date

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

                # DEBUG: Log changes to problematic dates
                if deadline.attribute.identifier in ['kaavaluonnos_esillaolo_aineiston_maaraaika', 'ehdotus_nahtaville_aineiston_maaraaika']:
                    log.warning(f"[DEBUG SAVE] _set_calculated_deadline MODIFYING {deadline.attribute.identifier}: old={old_value} -> new={new_value}, preview={preview}")
                    import traceback
                    log.warning(f"[DEBUG SAVE] Traceback: {''.join(traceback.format_stack()[-6:-1])}")

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
    def update_deadlines(self, user=None, initial=False, preview_attributes={}, confirmed_fields={}, timing_metrics=None):
        # DEBUG LOGGING FOR SAVE
        DEBUG_DATES = ['kaavaluonnos_esillaolo_aineiston_maaraaika', 'ehdotus_nahtaville_aineiston_maaraaika']
        log.warning(f"[DEBUG SAVE] update_deadlines called. preview_attributes keys: {list(preview_attributes.keys()) if preview_attributes else 'NONE'}")
        for d in DEBUG_DATES:
            if d in preview_attributes:
                log.warning(f"[DEBUG SAVE] {d} in preview_attributes = {preview_attributes.get(d)}")
            if d in self.attribute_data:
                log.warning(f"[DEBUG SAVE] {d} in attribute_data = {self.attribute_data.get(d)}")
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
        if generated_deadlines:
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

    def get_preview_deadlines(self, updated_attributes, subtype, confirmed_fields=None, timing_metrics=None):
        log.warning("[DEBUG PREVIEW] get_preview_deadlines() called")
        log.warning(f"[DEBUG PREVIEW] updated_attributes keys: {list(updated_attributes.keys()) if updated_attributes else 'NONE'}")
        log.warning(f"[DEBUG PREVIEW] confirmed_fields: {confirmed_fields}")
        log.warning(f"[DEBUG PREVIEW] subtype: {subtype}")
        
        confirmed_fields = confirmed_fields or []

        # Use request values over DB values to avoid stale data
        project_dls = {}
        for dl in self.deadlines.filter(deadline__subtype=subtype) \
            .select_related(
                "deadline", "deadline__phase", "deadline__phase__common_project_phase", "deadline__phase__project_subtype",
                "deadline__subtype", "deadline__attribute", "deadline__date_type") \
            .prefetch_related("deadline__initial_calculations","deadline__update_calculations"):
            deadline = dl.deadline
            # Use updated value from request if available, otherwise use database value
            if deadline.attribute and deadline.attribute.identifier in updated_attributes:
                project_dls[deadline] = updated_attributes[deadline.attribute.identifier]
            else:
                project_dls[deadline] = dl.date

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

        # Auto-enable visibility for new deadlines
        for dl in new_dls.keys():
            if dl.deadlinegroup:
                vis_bool = get_dl_vis_bool_name(dl.deadlinegroup)
                if vis_bool and vis_bool not in updated_attribute_data:
                    updated_attribute_data[vis_bool] = True
        
        # Respect explicit visibility booleans from frontend (False=deletion).
        # Don't auto-enable secondary slots (_2,_3,_4) when primary (_1) is disabled.
        # First, collect which primary vis_bools are explicitly disabled
        explicitly_disabled_primary = set()
        for key, value in updated_attributes.items():
            if key.endswith('_1') and value is False:
                # Extract base name (e.g. "periaatteet_lautakuntaan" from "periaatteet_lautakuntaan_1")
                base_name = key[:-2]  # Remove "_1"
                explicitly_disabled_primary.add(base_name)
        
        for dl in project_dls.keys():
            if not dl.deadlinegroup:
                continue
            vis_bool = get_dl_vis_bool_name(dl.deadlinegroup)
            if not vis_bool:
                continue
            
            # If frontend explicitly sent this visibility boolean, respect it - don't override
            if vis_bool in updated_attributes:
                continue
            
            # Check if this is a secondary slot (_2, _3, _4) whose primary (_1) was explicitly disabled
            if len(vis_bool) >= 2 and vis_bool[-2] == '_' and vis_bool[-1] in '234':
                base_name = vis_bool[:-2]  # Remove "_2", "_3", or "_4"
                if base_name in explicitly_disabled_primary:
                    continue
            
            # Check if date is being provided for this deadline in updated_attributes
            # BUT: Only auto-enable if the visibility was PREVIOUSLY True in the project.
            # If it was False, don't auto-enable just because the date exists.
            if dl.attribute:
                date_value = updated_attributes.get(dl.attribute.identifier)
                current_vis = updated_attribute_data.get(vis_bool)
                # Check what the STORED visibility was before this request
                stored_vis = self.attribute_data.get(vis_bool)
                if date_value and not current_vis:
                    # Only auto-enable if it was previously visible (True) or not yet set (None)
                    # If it was explicitly False in the database, keep it False
                    if stored_vis is False:
                        continue
                    # Date is being set for a disabled group - enable it
                    updated_attribute_data[vis_bool] = True

        # KAAV-3517: Determine which deadlines actually CHANGED value (not just sent by frontend)
        # The frontend sends all deadline values, but we only want to enforce distances
        # on deadlines where the user actually moved them (value differs from current)
        #
        # PHASE BOUNDARY FIX: Auto-calculated deadlines (edit_privilege is None) should NEVER
        # be added to actually_changed. Per AT1.2.1/AT1.2.3, users cannot edit phase start/end
        # dates - they move automatically. The frontend sends stale values for these, but we
        # must always recalculate them, not treat them as user changes.
        auto_calculated_identifiers = {
            dl.attribute.identifier for dl in project_dls.keys()
            if dl.attribute and dl.edit_privilege is None
        }
        
        actually_changed = set()
        for key, new_value in updated_attributes.items():
            # Skip auto-calculated deadlines - they should always be recalculated
            if key in auto_calculated_identifiers:
                continue
            old_value = self.attribute_data.get(key)
            old_coerced = self._coerce_date_value(old_value) if old_value else None
            new_coerced = self._coerce_date_value(new_value) if new_value else None
            if old_coerced != new_coerced:
                actually_changed.add(key)

        # When visibility bool changes False→True (group re-add), treat dates as "changed"
        # to ensure distance enforcement happens for re-added groups
        vis_bools_enabled = set()
        for key, new_value in updated_attributes.items():
            old_value = self.attribute_data.get(key)
            # Check if this is a visibility bool that changed from False/None to True
            if isinstance(new_value, bool) and new_value is True and old_value is not True:
                vis_bools_enabled.add(key)
        
        # For each deadline, if its visibility bool was just enabled, mark its date as "changed"
        for dl in sorted(project_dls.keys(), key=lambda x: x.index):
            if not dl.deadlinegroup or not dl.attribute:
                continue
            vis_bool = get_dl_vis_bool_name(dl.deadlinegroup)
            if vis_bool and vis_bool in vis_bools_enabled:
                identifier = dl.attribute.identifier
                
                # UX80.5.3.7: Confirmed deadlines must never move automatically
                if identifier in confirmed_fields:
                    continue
                
                # Check for stale date: Group enabled, but date matches stored value
                current_val = updated_attribute_data.get(identifier)
                stored_val = self.attribute_data.get(identifier)
                
                current_date = self._coerce_date_value(current_val)
                stored_date = self._coerce_date_value(stored_val)
                
                # Only apply calculate_initial() to truly NEW deadlines.
                # Re-enabled deadlines use distances_to_previous, not initial_calculations.
                if dl in new_dls and current_date and current_date == stored_date:
                    # UX80.4.2.3.3.2: Added element moves to initial distance (generoitu ehdotus)
                    # from its predecessor. Use calculate_initial() for the ADDED element only.
                    # The forward cascade will handle subsequent elements using distances_to_previous.
                    initial_date = dl.calculate_initial(self, preview_attributes=updated_attribute_data)
                    
                    # SPECIAL CASE (AT1.5.3): Opinions deadline ("viimeistaan_mielipiteet")
                    # defaults to matching "esillaolo_paattyy" if no initial_calculations exist
                    if not initial_date and "viimeistaan_mielipiteet" in identifier:
                        # Find sibling "esillaolo_paattyy" in same group
                        sibling = next((d for d in project_dls.keys() if d.deadlinegroup == dl.deadlinegroup and "esillaolo_paattyy" in (d.attribute.identifier if d.attribute else "")), None)
                        if sibling and sibling.attribute:
                            sib_id = sibling.attribute.identifier
                            sib_val = updated_attribute_data.get(sib_id) or self.attribute_data.get(sib_id)
                            if sib_val:
                                initial_date = self._coerce_date_value(sib_val)
                    
                    if initial_date:
                        log.warning("[DEBUG RE-ENABLE] NEW deadline '%s': calculate_initial -> %s (was %s)", 
                                    identifier, initial_date, current_date)
                        updated_attribute_data[identifier] = initial_date
                        project_dls[dl] = initial_date
                
                # RE-ENABLED deadlines (not new, but visibility just enabled): recalculate from predecessor
                # using distances_to_previous. This fixes stale dates from previous disable.
                # Only recalculate if current_date == stored_date (user hasn't moved it yet).
                elif dl not in new_dls and stored_date and current_date == stored_date:
                    # Recalculate this deadline from its predecessor(s) using distances_to_previous
                    combined = {**self.attribute_data, **updated_attribute_data}
                    recalc_target = None
                    for dist in dl.distances_to_previous.all():
                        if not dist.check_conditions(combined):
                            continue
                        prev_date = self._resolve_deadline_date(dist.previous_deadline, updated_attribute_data)
                        prev_date = self._coerce_date_value(prev_date)
                        if not prev_date:
                            continue
                        target = self._min_distance_target_date(prev_date, dist, dl)
                        # Use FIRST matching predecessor (not MAX) for the deadline's own recalculation
                        if target:
                            recalc_target = target
                            break
                    
                    if recalc_target and recalc_target != stored_date:
                        log.warning("[DEBUG RE-ENABLE] RE-ENABLED deadline '%s': recalculated %s -> %s (from predecessor)", 
                                    identifier, stored_date, recalc_target)
                        updated_attribute_data[identifier] = recalc_target
                        project_dls[dl] = recalc_target

                # Re-enabled groups: treat dates as changed to trigger distance enforcement
                actually_changed.add(identifier)

        # Recalculate deadlines with conditional predecessors referencing enabled vis_bools
        if vis_bools_enabled:
            log.warning("[DEBUG CASCADE] vis_bools_enabled = %s", vis_bools_enabled)
            from projects.models.deadline import DeadlineDistanceConditionAttribute, Attribute as DlAttribute
            
            # Find all condition attributes that reference the enabled visibility booleans
            condition_attrs = DeadlineDistanceConditionAttribute.objects.filter(
                attribute__identifier__in=vis_bools_enabled
            ).select_related('attribute').prefetch_related(
                'deadline_distances',
                'deadline_distances__deadline',
                'deadline_distances__deadline__attribute',
                'deadline_distances__previous_deadline',
                'deadline_distances__previous_deadline__attribute',
            )
            
            # Collect all deadlines affected by these conditional distance rules
            for cond_attr in condition_attrs:
                for distance in cond_attr.deadline_distances.all():
                    affected_dl = distance.deadline
                    if not affected_dl or not affected_dl.attribute:
                        continue
                    if affected_dl not in project_dls:
                        continue
                    
                    identifier = affected_dl.attribute.identifier
                    current_val = updated_attribute_data.get(identifier)
                    current_date = self._coerce_date_value(current_val)
                    
                    if not current_date:
                        continue
                    
                    # Recalculate the minimum target date based on NEW active predecessors
                    combined = {**self.attribute_data, **updated_attribute_data}
                    log.warning("[DEBUG CASCADE] Processing affected deadline '%s' BEFORE = %s", identifier, current_date)
                    max_target = None
                    
                    for dist in affected_dl.distances_to_previous.all():
                        prev_id = dist.previous_deadline.attribute.identifier if dist.previous_deadline and dist.previous_deadline.attribute else "NO_ID"
                        cond_result = dist.check_conditions(combined)
                        log.warning("[DEBUG CASCADE]   -> predecessor '%s' check_conditions = %s (distance_id=%s)", prev_id, cond_result, dist.id)
                        if not cond_result:
                            continue
                        prev_date = self._resolve_deadline_date(dist.previous_deadline, updated_attribute_data)
                        prev_date = self._coerce_date_value(prev_date)
                        log.warning("[DEBUG CASCADE]      prev_date = %s, distance_days = %s", prev_date, getattr(dist, 'distance_from_previous', 'N/A'))
                        if not prev_date:
                            continue
                        target = self._min_distance_target_date(prev_date, dist, affected_dl)
                        log.warning("[DEBUG CASCADE]      calculated target = %s (current max_target = %s)", target, max_target)
                        if target and (not max_target or target > max_target):
                            log.warning("[DEBUG CASCADE]      ** UPDATING max_target from %s to %s **", max_target, target)
                            max_target = target
                    
                    # If current date is BEFORE new minimum, enforce forward
                    if max_target and current_date < max_target:
                        log.warning("[DEBUG CASCADE] RESULT '%s': ENFORCED forward %s -> %s (delta = %s days)", 
                                    identifier, current_date, max_target, (max_target - current_date).days)
                        updated_attribute_data[identifier] = max_target
                        project_dls[affected_dl] = max_target
                        actually_changed.add(identifier)
                    elif max_target and identifier not in actually_changed:
                        log.warning("[DEBUG CASCADE] RESULT '%s': no enforcement needed (current %s >= max_target %s)", 
                                    identifier, current_date, max_target)
                        actually_changed.add(identifier)

        for dl in project_dls.keys():
            if not dl.attribute:
                continue

            value = updated_attribute_data.get(dl.attribute.identifier)
            identifier = dl.attribute.identifier

            if value:
                # Only enforce distances on deadlines that actually changed AND violate minimum
                if identifier in actually_changed:
                    current_date = self._coerce_date_value(value)
                    needs_enforcement = False

                    if current_date:
                        for distance in dl.distances_to_previous.all():
                            combined = {**self.attribute_data, **updated_attribute_data}
                            if not distance.check_conditions(combined):
                                continue
                            prev_date = self._resolve_deadline_date(distance.previous_deadline, updated_attribute_data)
                            prev_date = self._coerce_date_value(prev_date)
                            if not prev_date:
                                continue
                            min_target = self._min_distance_target_date(prev_date, distance, dl)
                            if min_target and current_date < min_target:
                                needs_enforcement = True
                                break

                    if needs_enforcement:
                        enforced_value = self._enforce_distance_requirements(
                            dl,
                            value,
                            preview_attribute_data=updated_attribute_data,
                        )
                        project_dls[dl] = enforced_value
                        if enforced_value and enforced_value != value:
                            updated_attribute_data[dl.attribute.identifier] = enforced_value
                    else:
                        # Snap to valid date_type even when distance is satisfied
                        snapped_value = value
                        if dl.date_type:
                            coerced = self._coerce_date_value(value)
                            if coerced:
                                valid_date = dl.date_type.get_closest_valid_date(coerced)
                                if valid_date and valid_date != coerced:
                                    snapped_value = valid_date
                                    updated_attribute_data[dl.attribute.identifier] = valid_date
                        project_dls[dl] = snapped_value
                else:
                    # Snap unchanged deadlines to valid date_type
                    snapped_value = value
                    if dl.date_type:
                        coerced = self._coerce_date_value(value)
                        if coerced:
                            valid_date = dl.date_type.get_closest_valid_date(coerced)
                            if valid_date and valid_date != coerced:
                                snapped_value = valid_date
                                updated_attribute_data[dl.attribute.identifier] = valid_date
                    project_dls[dl] = snapped_value

        # Forward cascade: push subsequent deadlines if they violate distance rules
        dl_to_identifier = {dl: dl.attribute.identifier for dl in project_dls.keys() if dl.attribute}
        identifier_to_dl = {v: k for k, v in dl_to_identifier.items()}
        
        # Track which deadlines were changed (either by user or by enforcement)
        changed_identifiers = set(actually_changed)
        
        # Iterate until no more changes (cascade propagation)
        # Max iterations = number of deadlines (worst case: linear dependency chain)
        max_iterations = len(project_dls)
        iteration = 0
        for iteration in range(1, max_iterations + 1):
            new_changes = set()
            
            for changed_id in changed_identifiers:
                if changed_id not in identifier_to_dl:
                    continue
                changed_dl = identifier_to_dl[changed_id]
                changed_date = self._coerce_date_value(updated_attribute_data.get(changed_id))
                if not changed_date:
                    continue
                
                # Check all deadlines that have a distance rule FROM this deadline
                for distance in changed_dl.distances_to_next.all():
                    next_dl = distance.deadline
                    if not next_dl.attribute:
                        continue
                    next_id = next_dl.attribute.identifier
                    
                    # Skip if next deadline is not in our working set (not visible/applicable)
                    if next_dl not in project_dls:
                        continue
                    
                    # Check if distance conditions are met
                    combined = {**self.attribute_data, **updated_attribute_data}
                    if not distance.check_conditions(combined):
                        continue
                    
                    next_date = self._coerce_date_value(updated_attribute_data.get(next_id))
                    if not next_date:
                        next_date = self._coerce_date_value(project_dls.get(next_dl))
                    if not next_date:
                        continue
                    
                    # Find maximum minimum target across ALL predecessors
                    max_min_target = None
                    for dist in next_dl.distances_to_previous.all():
                        if not dist.check_conditions(combined):
                            continue
                        prev_date = self._resolve_deadline_date(dist.previous_deadline, updated_attribute_data)
                        prev_date = self._coerce_date_value(prev_date)
                        if not prev_date:
                            continue
                        target = self._min_distance_target_date(prev_date, dist, next_dl)
                        if target and (not max_min_target or target > max_min_target):
                            max_min_target = target
                    
                    if not max_min_target:
                        continue
                    
                    # Push forward if violating any predecessor distance
                    if next_date < max_min_target:
                        enforced_date = self._enforce_distance_requirements(
                            next_dl,
                            max_min_target,
                            preview_attribute_data=updated_attribute_data,
                        )
                        if enforced_date and enforced_date != next_date:
                            updated_attribute_data[next_id] = enforced_date
                            project_dls[next_dl] = enforced_date
                            new_changes.add(next_id)
            
            if not new_changes:
                break
            
            changed_identifiers = new_changes
        
        if max_iterations > 0 and iteration >= max_iterations:
            log.warning(f"Cascade hit max iterations ({max_iterations}), possible cycle")

        # Generate newly added deadlines
        calculation_cache = {}

        new_dls_to_calc = [
            dl for dl in new_dls.keys()
            if dl.initial_calculations.exists() or dl.default_to_created_at
        ]

        initial_calc_results = self._set_calculated_deadlines(
            new_dls_to_calc,
            None,
            initial=True,
            preview=True,
            preview_attribute_data=updated_attribute_data,
            confirmed_fields=confirmed_fields,
            calculation_cache=calculation_cache,
            timing_metrics=timing_metrics,
            user_changed_fields=actually_changed,
        )
        
        project_dls = {**project_dls, **initial_calc_results}
        
        # Propagate initial_calc results so phase boundaries use new inner deadline values
        for dl, result in initial_calc_results.items():
            if hasattr(dl, 'attribute') and dl.attribute:
                identifier = dl.attribute.identifier
                result_coerced = self._coerce_date_value(result)
                if result_coerced:
                    old_val = updated_attribute_data.get(identifier)
                    old_val_coerced = self._coerce_date_value(old_val)
                    if old_val_coerced != result_coerced:
                        updated_attribute_data[identifier] = result_coerced
        
        # Recalculate deadlines with update_calculations (exclude user-changed ones)
        update_dls_to_calc = [
            dl for dl in project_dls
            if (dl.update_calculations.exists() or dl.default_to_created_at)
            and not (dl.attribute and dl.attribute.identifier in actually_changed)
        ]

        # Unified convergence loop: recalculate phases, enforce distances, cascade
        max_convergence_iterations = 10
        
        # Deadlines processed by update_calculations are "calculated deadlines"
        calculated_dl_identifiers = {
            dl.attribute.identifier for dl in update_dls_to_calc 
            if hasattr(dl, 'attribute') and dl.attribute
        }

        for convergence_iteration in range(1, max_convergence_iterations + 1):
            iteration_changes = set()
            
            # Step 1: Recalculate phase boundaries
            # We MUST clear the cache to ensure new values are used
            calculation_cache = {}
            
            recalc_results = self._set_calculated_deadlines(
                update_dls_to_calc,
                None,
                initial=False,
                preview=True,
                preview_attribute_data=updated_attribute_data,
                confirmed_fields=confirmed_fields,
                calculation_cache=calculation_cache,
                timing_metrics=timing_metrics,
                user_changed_fields=actually_changed,
            )
            project_dls = {**project_dls, **recalc_results}
            
            # Detect changes from recalculation
            for dl, new_date in recalc_results.items():
                if not hasattr(dl, 'attribute') or not dl.attribute:
                    continue
                identifier = dl.attribute.identifier
                old_date = self._coerce_date_value(updated_attribute_data.get(identifier))
                new_date_coerced = self._coerce_date_value(new_date)
                
                # Update if different or if new value is set for the first time
                if (new_date_coerced and old_date != new_date_coerced) or \
                   (new_date_coerced and not old_date):
                    updated_attribute_data[identifier] = new_date_coerced
                    iteration_changes.add(identifier)
            
            # Step 2 & 3: Enforce attribute-only deadlines AND Cascade
            # We mix these because a push might trigger an enforcement, which triggers a recalc
            
            # Start queue with changes from Step 1
            cascade_queue = iteration_changes.copy()
            
            # Also check ALL attribute-only deadlines for violations in every iteration
            # This catches cases like T3 (attribute-only) needing to move because T2 moved
            for dl in project_dls.keys():
                if not hasattr(dl, 'attribute') or not dl.attribute:
                    continue
                identifier = dl.attribute.identifier
                if identifier in calculated_dl_identifiers:
                    continue # Handled by recalc
                if identifier in cascade_queue:
                    continue # Already in queue
                
                current_date = self._coerce_date_value(updated_attribute_data.get(identifier))
                if not current_date:
                    continue
                    
                for distance in dl.distances_to_previous.all():
                    combined = {**self.attribute_data, **updated_attribute_data}
                    if not distance.check_conditions(combined):
                        continue
                    prev_date = self._resolve_deadline_date(distance.previous_deadline, updated_attribute_data)
                    prev_date = self._coerce_date_value(prev_date)
                    if not prev_date:
                        continue
                    min_target = self._min_distance_target_date(prev_date, distance, dl)
                    if min_target and current_date < min_target:
                        # Skip confirmed fields
                        if confirmed_fields and identifier in confirmed_fields:
                            continue

                        cascade_queue.add(identifier)
                        break

            if cascade_queue:
                for _ in range(1, 11):
                    new_cascade_changes = set()
                    
                    for changed_id in cascade_queue:
                        # 1. Enforce self (if not calculated)
                        changed_dl = identifier_to_dl.get(changed_id)
                        if not changed_dl:
                            continue
                            
                        current_val = updated_attribute_data.get(changed_id)
                        current_date = self._coerce_date_value(current_val)
                        
                        if changed_id not in calculated_dl_identifiers and current_date:

                            for distance in changed_dl.distances_to_previous.all():
                                combined = {**self.attribute_data, **updated_attribute_data}
                                if not distance.check_conditions(combined):
                                    continue
                                prev_date = self._resolve_deadline_date(distance.previous_deadline, updated_attribute_data)
                                prev_date = self._coerce_date_value(prev_date)
                                if not prev_date:
                                    continue
                                min_target = self._min_distance_target_date(prev_date, distance, changed_dl)
                                if min_target and current_date < min_target:
                                    if confirmed_fields and changed_id in confirmed_fields:
                                        continue
                                    enforced = self._enforce_distance_requirements(changed_dl, min_target, updated_attribute_data)
                                    if enforced and enforced != current_date:
                                        updated_attribute_data[changed_id] = enforced
                                        project_dls[changed_dl] = enforced
                                        iteration_changes.add(changed_id)
                                        current_date = enforced 
                        
                        # 2. Push dependents (Forward Cascade)
                        if not current_date:
                            continue

                        for distance in changed_dl.distances_to_next.all():
                            next_dl = distance.deadline
                            if not next_dl.attribute:
                                continue
                            next_id = next_dl.attribute.identifier
                            if next_dl not in project_dls:
                                continue
                            
                            combined = {**self.attribute_data, **updated_attribute_data}
                            if not distance.check_conditions(combined):
                                continue
                                
                            next_val = updated_attribute_data.get(next_id)
                            if not next_val:
                                next_val = project_dls.get(next_dl)
                                
                            next_date = self._coerce_date_value(next_val)
                            if not next_date:
                                continue
                                
                            min_target = self._min_distance_target_date(current_date, distance, next_dl)
                            if min_target and next_date < min_target:
                                if confirmed_fields and next_id in confirmed_fields:
                                    continue
                                new_cascade_changes.add(next_id)
                                iteration_changes.add(next_id)
                                updated_attribute_data[next_id] = min_target
                                project_dls[next_dl] = min_target

                    if not new_cascade_changes:
                        break
                    cascade_queue = new_cascade_changes

            # Check if converged
            if not iteration_changes:
                break
        
        if convergence_iteration >= max_convergence_iterations:
            log.warning(f"Convergence hit max iterations ({max_convergence_iterations})")

        # Add visibility booleans
        for identifier, value in updated_attribute_data.items():
            if type(value) == bool:
                project_dls[identifier] = value
        
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
