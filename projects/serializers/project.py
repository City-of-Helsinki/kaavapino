import copy
import datetime
import numpy as np
from typing import List, NamedTuple, Type

from actstream import action
from django.contrib.auth import get_user_model
from django.core.exceptions import ObjectDoesNotExist
from django.core.serializers.json import DjangoJSONEncoder, json
from django.db import transaction
from django.db.models import Prefetch, Q
from django.utils.translation import ugettext_lazy as _
from rest_framework import serializers
from rest_framework.exceptions import ValidationError, NotFound, ParseError
from rest_framework.serializers import Serializer
from rest_framework_gis.fields import GeometryField

from projects.actions import verbs
from projects.models import (
    Project,
    ProjectSubtype,
    ProjectPhase,
    ProjectPhaseLog,
    ProjectPhaseSection,
    ProjectPhaseDeadlineSection,
    ProjectFloorAreaSection,
    ProjectAttributeFile,
    ProjectDeadline,
    Attribute,
    ProjectPhaseSectionAttribute,
    ProjectComment,
    Deadline,
    DeadlineDateCalculation,
    ProjectAttributeFileFieldsetPathLocation,
)
from projects.models.project import ProjectAttributeMultipolygonGeometry
from projects.permissions.media_file_permissions import (
    has_project_attribute_file_permissions,
)
from projects.serializers.utils import _set_fieldset_path
from projects.serializers.fields import AttributeDataField
from projects.serializers.section import create_section_serializer
from projects.serializers.deadline import DeadlineSerializer
from sitecontent.models import ListViewAttributeColumn
from users.models import User
from users.serializers import UserSerializer


class SectionData(NamedTuple):
    section: ProjectPhaseSection
    serializer_class: Type[Serializer]


class ProjectDeadlineSerializer(serializers.Serializer):
    past_due = serializers.SerializerMethodField()
    out_of_sync = serializers.SerializerMethodField()
    is_under_min_distance_previous = serializers.SerializerMethodField()
    is_under_min_distance_next = serializers.SerializerMethodField()
    date = serializers.DateField()
    abbreviation = serializers.CharField(source="deadline.abbreviation")
    deadline = serializers.SerializerMethodField()
    generated = serializers.BooleanField()

    def get_deadline(self, projectdeadline):
        return DeadlineSerializer(
            projectdeadline.deadline
        ).data

    def _resolve_distance_conditions(self, distance, project):
        if distance.conditions.count() == 0:
            return True

        for attribute in distance.conditions.all():
            if project.attribute_data.get(attribute.identifier):
                return True

        return False

    def get_is_under_min_distance_next(self, projectdeadline):
        if not projectdeadline.date:
            return False

        next_deadlines = projectdeadline.deadline.distances_to_next.all()
        for next_distance in next_deadlines:
            # Ignore if distance conditions are not met
            if not self._resolve_distance_conditions(
                next_distance,
                projectdeadline.project,
            ):
                continue

            # Ignore if next deadline does not exist for project
            try:
                next_date = projectdeadline.project.deadlines.get(
                    deadline=next_distance.deadline
                ).date
            except ProjectDeadline.DoesNotExist:
                continue

            # Ignore if next date is not set
            if not next_date:
                continue

            if next_distance.date_type:
                distance_to_next = next_distance.date_type.valid_days_to(
                    projectdeadline.date, next_date
                )
            else:
                distance_to_next = (next_date - projectdeadline.date).days
            if distance_to_next < next_distance.distance_from_previous:
                return True

        return False

    def get_is_under_min_distance_previous(self, projectdeadline):
        if not projectdeadline.date:
            return False

        prev_deadlines = projectdeadline.deadline.distances_to_previous.all()
        for prev_distance in prev_deadlines:
            # Ignore if distance conditions are not met
            if not self._resolve_distance_conditions(
                prev_distance,
                projectdeadline.project,
            ):
                continue

            # Ignore if previous deadline does not exist for project
            try:
                prev_date = projectdeadline.project.deadlines.get(
                    deadline=prev_distance.previous_deadline
                ).date
            except ProjectDeadline.DoesNotExist:
                continue

            # Ignore if previous date is not set
            if not prev_date:
                continue

            if prev_distance.date_type:
                distance_from_prev = prev_distance.date_type.valid_days_to(
                    prev_date, projectdeadline.date
                )
            else:
                distance_from_prev = (projectdeadline.date - prev_date).days
            if distance_from_prev < prev_distance.distance_from_previous:
                return True

        return False

    def get_past_due(self, projectdeadline):
        return len([
            dl for dl in projectdeadline.project.deadlines.filter(
                deadline__index__lte=projectdeadline.deadline.index,
                date__lt=datetime.date.today(),
            )
            if not dl.confirmed
        ]) > 0

    def get_out_of_sync(self, projectdeadline):
        return projectdeadline.project.subtype != \
            projectdeadline.deadline.phase.project_subtype

    class Meta:
        model = ProjectDeadline
        fields = [
            "date",
            "abbreviation",
            "deadline_id",
            "past_due",
            "is_under_min_distance_previous",
            "is_under_min_distance_next",
            "out_of_sync",
            "distance_reference_deadline_id",
        ]


class ProjectListSerializer(serializers.ModelSerializer):
    user = serializers.SlugRelatedField(
        read_only=False, slug_field="uuid", queryset=get_user_model().objects.all()
    )
    attribute_data = AttributeDataField(allow_null=True, required=False)
    type = serializers.SerializerMethodField()
    phase_start_date = serializers.SerializerMethodField()

    class Meta:
        model = Project
        fields = [
            "user",
            "created_at",
            "modified_at",
            "name",
            "identifier",
            "pino_number",
            "type",
            "subtype",
            "attribute_data",
            "phase",
            "id",
            "public",
            "owner_edit_override",
            "archived",
            "onhold",
            "create_principles",
            "create_draft",
            "phase_start_date",
        ]

    def get_type(self, project):
        return project.type.pk

    def get_phase_start_date(self, project):
        try:
            return project.deadlines \
                .filter(deadline__phase=project.phase) \
                .order_by("deadline__index").first().date
        except AttributeError:
            return None

    def get_attribute_data(self, project):
        static_properties = [
            "user",
            "name",
            "public",
            "pino_number",
            "create_principles",
            "create_draft",
        ]
        return_data = {}
        attrs = ListViewAttributeColumn.objects.all().select_related("attribute")
        attribute_data = getattr(project, "attribute_data", {})
        for attr in attrs:
            identifier = attr.attribute.identifier
            value = attribute_data.get(identifier)
            if attr.attribute.static_property in static_properties:
                return_data[identifier] = getattr(
                    project, attr.attribute.static_property
                )
            elif value:
                return_data[identifier] = value

        return_data['kaavaprosessin_kokoluokka'] = project.phase.project_subtype.name

        return return_data


class ProjectSerializer(serializers.ModelSerializer):
    user = serializers.SlugRelatedField(
        read_only=False, slug_field="uuid", queryset=get_user_model().objects.all()
    )
    attribute_data = AttributeDataField(allow_null=True, required=False)
    type = serializers.SerializerMethodField()
    deadlines = serializers.SerializerMethodField()
    public = serializers.NullBooleanField(required=False, read_only=True)
    owner_edit_override = serializers.NullBooleanField(required=False, read_only=True)
    archived = serializers.NullBooleanField(required=False, read_only=True)
    onhold = serializers.NullBooleanField(required=False, read_only=True)
    generated_deadline_attributes = serializers.SerializerMethodField()

    _metadata = serializers.SerializerMethodField()

    class Meta:
        model = Project
        fields = [
            "user",
            "created_at",
            "modified_at",
            "name",
            "identifier",
            "pino_number",
            "type",
            "subtype",
            "attribute_data",
            "phase",
            "id",
            "public",
            "owner_edit_override",
            "archived",
            "onhold",
            "deadlines",
            "create_principles",
            "create_draft",
            "generated_deadline_attributes",
            "_metadata",
        ]
        read_only_fields = ["type", "created_at", "modified_at"]

    def _get_snapshot_date(self, project):
        query_params = getattr(self.context["request"], "GET", {})
        snapshot_param = query_params.get("snapshot")
        snapshot = None

        if snapshot_param:
            try:
                return ProjectPhaseLog.objects.filter(
                    phase__id=int(snapshot_param),
                    project=project,
                ).order_by("-created_at").first().created_at
            except AttributeError:
                raise NotFound(detail=_("Project data at selected phase start cannot be found"))
            except ValueError:
                pass

            try:
                snapshot = datetime.datetime.strptime(
                    snapshot_param,
                    "%Y-%m-%dT%H:%M:%S.%fZ%z",
                )
            except ValueError:
                try:
                    snapshot = datetime.datetime.strptime(
                        snapshot_param[:-3]+snapshot_param[-2:],
                        "%Y-%m-%dT%H:%M:%S%z",
                    )
                except ValueError:
                    raise ParseError(detail=_("Incorrect snapshot datetime format, use one of the following:\n%Y-%m-%dT%H:%M:%S.%fZ%z\n\nphase id"))

            if snapshot < project.created_at:
                raise NotFound(detail=_("Project data at selected date cannot be found"))

            return snapshot

        return None

    def get_fields(self):
        fields = super(ProjectSerializer, self).get_fields()
        request = self.context.get('request', None)

        try:
            if request.user.uuid == self.instance.user.uuid:
                fields["public"] = serializers.NullBooleanField(required=False)
                fields["onhold"] = serializers.NullBooleanField(required=False)
        except AttributeError:
            pass

        return fields

    def get_attribute_data(self, project):
        snapshot = self._get_snapshot_date(project)

        if snapshot:
            attribute_data = {
                k: v["new_value"]
                for k, v in self._get_updates(project, cutoff=snapshot).items()
            }
        else:
            attribute_data = getattr(project, "attribute_data", {})

        self._set_file_attributes(attribute_data, project, snapshot)

        # TODO handle snapshot case
        self._set_geometry_attributes(attribute_data, project)

        if snapshot:
            try:
                subtype = ProjectPhaseLog.objects.filter(
                    created_at__lte=self._get_snapshot_date(project),
                    project=project
                ).order_by("-created_at").first().phase.project_subtype
            except AttributeError:
                subtype = project.phase.project_subtype
            attribute_data['kaavaprosessin_kokoluokka'] = subtype.name
        else:
            attribute_data['kaavaprosessin_kokoluokka'] = \
                project.phase.project_subtype.name

        static_properties = [
            "user",
            "name",
            "public",
            "pino_number",
            "create_principles",
            "create_draft",
        ]


        if not snapshot:
            for static_property in static_properties:
                try:
                    identifier = \
                        Attribute.objects.get(static_property=static_property).identifier
                    attribute_data[identifier] = getattr(project, static_property)
                except Attribute.DoesNotExist:
                    continue

        return attribute_data

    def get_type(self, project):
        return project.type.pk

    def get_deadlines(self, project):
        deadlines = project.deadlines.filter(deadline__subtype=project.subtype)
        return ProjectDeadlineSerializer(
            deadlines,
            many=True,
            allow_null=True,
            required=False,
        ).data

    def get_generated_deadline_attributes(self, project):
        return [
            dl.deadline.attribute.identifier
            for dl in project.deadlines.filter(generated=True)
            if dl.deadline.attribute
        ]

    def _set_file_attributes(self, attribute_data, project, snapshot):
        request = self.context["request"]
        if snapshot:
            attribute_files = ProjectAttributeFile.objects \
                .filter(project=project, created_at__lte=snapshot) \
                .exclude(archived_at__lte=snapshot) \
                .order_by(
                    "fieldset_path_str",
                    "attribute__pk",
                    "project__pk",
                    "-created_at",
                ) \
                .distinct("fieldset_path_str", "attribute__pk", "project__pk")
        else:
            attribute_files = ProjectAttributeFile.objects \
                .filter(project=project, archived_at=None) \
                .order_by(
                    "fieldset_path_str",
                    "attribute__pk",
                    "project__pk",
                    "-created_at",
                ) \
                .distinct("fieldset_path_str", "attribute__pk", "project__pk")

        # Add file attributes to the attribute data
        # File values are represented as absolute URLs
        file_attributes = {}
        for attribute_file in attribute_files:
            if has_project_attribute_file_permissions(attribute_file, request):
                if not attribute_file.fieldset_path:
                    file_attributes[attribute_file.attribute.identifier] = {
                        "link": request.build_absolute_uri(attribute_file.file.url),
                        "description": attribute_file.description,
                    }
                else:
                    _set_fieldset_path(
                        attribute_file.fieldset_path,
                        file_attributes,
                        0,
                        attribute_file.attribute.identifier,
                        {
                            "link": request.build_absolute_uri(attribute_file.file.url),
                            "description": attribute_file.description,
                        }
                    )
        attribute_data.update(file_attributes)

    @staticmethod
    def _set_geometry_attributes(attribute_data, project):
        attribute_geometries = ProjectAttributeMultipolygonGeometry.objects.filter(
            project=project
        )

        geometry_attributes = {
            attribute_geometry.attribute.identifier: GeometryField().to_representation(
                value=attribute_geometry.geometry
            )
            for attribute_geometry in attribute_geometries
        }
        attribute_data.update(geometry_attributes)

    def get__metadata(self, project):
        list_view = self.context.get("action", None) == "list"
        metadata = {"users": self._get_users(project, list_view=list_view)}
        query_params = getattr(self.context["request"], "GET", {})
        snapshot_param = query_params.get("snapshot")
        if not list_view and not snapshot_param:
            metadata["updates"] = self._get_updates(project)

        return metadata

    @staticmethod
    def _get_users(project, list_view=False):
        users = [project.user]

        if not list_view:
            attributes = Attribute.objects.filter(
                value_type__in=[Attribute.TYPE_USER, Attribute.TYPE_FIELDSET]
            ).prefetch_related(
                Prefetch(
                    "fieldset_attributes",
                    queryset=Attribute.objects.filter(value_type=Attribute.TYPE_USER),
                )
            )

            user_attribute_ids = set()
            for attribute in attributes:
                if attribute.value_type == Attribute.TYPE_FIELDSET:
                    fieldset_user_identifiers = attribute.fieldset_attributes.all().values_list(
                        "identifier", flat=True
                    )
                    if attribute.identifier in project.attribute_data:
                        user_attribute_ids |= ProjectSerializer._get_fieldset_attribute_values(
                            project, attribute, fieldset_user_identifiers
                        )
                else:
                    user_id = project.attribute_data.get(attribute.identifier, None)
                    if user_id:
                        user_attribute_ids.add(user_id)

            # Do not include the user of the project
            if str(project.user.uuid) in user_attribute_ids:
                user_attribute_ids.remove(str(project.user.uuid))

            users += list(User.objects.filter(uuid__in=user_attribute_ids))

        return UserSerializer(users, many=True).data

    @staticmethod
    def _get_fieldset_attribute_values(
        project, fieldset_attribute, fieldset_identifiers
    ):
        values = set()
        for entry in project.attribute_data[fieldset_attribute.identifier]:
            for identifier in fieldset_identifiers:
                value = entry.get(identifier, None)
                if value:
                    values.add(value)

        return values

    @staticmethod
    def _get_updates(project, cutoff=None):
        # Get the latest attribute updates for distinct attributes
        if cutoff:
            actions = (
                project.target_actions.filter(
                    verb=verbs.UPDATED_ATTRIBUTE,
                    timestamp__lte=cutoff,
                )
                .order_by(
                    "data__attribute_identifier",
                    "action_object_content_type",
                    "action_object_object_id",
                    "-timestamp",
                )
                .distinct(
                    "data__attribute_identifier",
                    "action_object_content_type",
                    "action_object_object_id",
                )

                .prefetch_related("actor")
            )
        else:
            actions = (
                project.target_actions.filter(verb=verbs.UPDATED_ATTRIBUTE)
                .order_by(
                    "data__attribute_identifier",
                    "action_object_content_type",
                    "action_object_object_id",
                    "-timestamp",
                )
                .distinct(
                    "data__attribute_identifier",
                    "action_object_content_type",
                    "action_object_object_id",
                )

                .prefetch_related("actor")
            )

        updates = {}
        for _action in actions:
            attribute_identifier = (
                _action.data.get("attribute_identifier", None)
                or _action.action_object.identifier
            )
            updates[attribute_identifier] = {
                "user": _action.actor.uuid,
                "user_name": _action.actor.get_display_name(),
                "timestamp": _action.timestamp,
                "new_value": _action.data.get("new_value", None),
                "old_value": _action.data.get("old_value", None),
            }

        return updates

    def should_validate_attributes(self):
        validate_field_data = self.context["request"].data.get(
            "validate_attribute_data", False
        )
        return serializers.BooleanField().to_internal_value(validate_field_data)

    def generate_sections_data(
        self,
        phase: ProjectPhase,
        preview,
        validation: bool = True,
    ) -> List[SectionData]:
        sections = []
        for section in phase.sections.order_by("index"):
            serializer_class = create_section_serializer(
                section,
                context=self.context,
                project=self.instance,
                validation=validation,
                preview=preview,
            )
            section_data = SectionData(section, serializer_class)
            sections.append(section_data)

        return sections

    def generate_floor_area_sections_data(
        self, floor_area_sections, preview, validation: bool = True
    ) -> List[SectionData]:
        sections = []
        for section in floor_area_sections.order_by("index"):
            serializer_class = create_section_serializer(
                section,
                context=self.context,
                project=self.instance,
                validation=validation,
                preview=preview,
            )
            section_data = SectionData(section, serializer_class)
            sections.append(section_data)

        return sections

    def generate_schedule_sections_data(self, phase, preview, validation=True):
        sections = []
        deadline_sections = phase.deadline_sections.all()
        for section in deadline_sections:
            serializer_class = create_section_serializer(
                section,
                context=self.context,
                project=self.instance,
                validation=validation,
                preview=preview,
            )
            section_data = SectionData(section, serializer_class)
            sections.append(section_data)

        return sections

    def validate(self, attrs):
        archived = attrs.get('archived')
        was_archived = self.instance and self.instance.archived

        if archived is not False and was_archived:
            raise ValidationError(
                {"phase": _("Archived projects cannot be edited")}
            )

        if attrs.get("subtype") and self.instance is not None:
            attrs["phase"] = self._validate_phase(attrs)

        public = self._validate_public(attrs)

        if public:
            attrs["public"] = public

        attrs["owner_edit_override"] = self._validate_owner_edit_override(attrs)

        subtype = attrs.get("subtype")
        if not subtype and self.instance:
            subtype = self.instance.subtype

        if attrs.get("create_principles") or attrs.get("create_draft"):
            if subtype and subtype.name != "XL":
                raise ValidationError({"subtype": _("Principles and drafts can only be created for XL projects.")})
        elif attrs.get("create_principles") == False and \
            attrs.get("create_draft") == False:
            if subtype and subtype.name == "XL":
                raise ValidationError({"subtype": _("Principles and/or draft needs to be created for XL projects.")})

        attrs["attribute_data"] = self._validate_attribute_data(
            attrs.get("attribute_data", None),
            attrs,
            self.instance.user if self.instance else None,
            self.instance.owner_edit_override if self.instance else None,
        )

        return attrs

    def _get_should_update_deadlines(self, subtype_changed, instance, attribute_data):
        if subtype_changed:
            should_update_deadlines = False
        elif instance:
            attr_identifiers = list(attribute_data.keys())
            should_update_deadlines = bool(
                instance.deadlines.prefetch_related("deadline").filter(
                    deadline__attribute__identifier__in=attr_identifiers
                ).count()
            )

            if not should_update_deadlines:
                should_update_deadlines= bool(DeadlineDateCalculation.objects.filter(
                    deadline__project_deadlines__project=instance
                ).filter(
                    Q(conditions__identifier__in=attr_identifiers) | \
                    Q(not_conditions__identifier__in=attr_identifiers) | \
                    Q(datecalculation__base_date_attribute__identifier__in=attr_identifiers) | \
                    Q(datecalculation__attributes__attribute__identifier__in=attr_identifiers)
                ).count())

        return should_update_deadlines

    def _validate_attribute_data(self, attribute_data, validate_attributes, user, owner_edit_override):
        static_property_attributes = {}
        if self.instance:
            static_properties = [
                "user",
                "name",
                "public",
                "pino_number",
                "create_principles",
                "create_draft",
            ]
            for static_property in static_properties:
                try:
                    try:
                        attr = validate_attributes[static_property]
                    except KeyError:
                        continue

                    static_property_attributes[
                        Attribute.objects.get(static_property=static_property).identifier
                    ] = attr
                except Attribute.DoesNotExist:
                    continue

        if not attribute_data:
            return static_property_attributes

        # Get serializers for all sections in all phases
        sections_data = []
        current_phase = getattr(self.instance, "phase", None)
        subtype = getattr(self.instance, "subtype", None) or \
            validate_attributes.get("subtype")
            # TODO: check if this subtype should be an attribute of phase object instead
            #validate_attributes.get("phase").project_subtype
        should_validate = self.should_validate_attributes()
        min_phase_index = current_phase.index if current_phase else 1

        try:
            is_owner = self.context["request"].user == self.user
            if owner_edit_override and is_owner:
                min_phase_index = 1
        except AttributeError:
            pass

        should_update_deadlines = self._get_should_update_deadlines(
            False, self.instance, attribute_data,
        )
        preview = None
        if self.instance and should_update_deadlines:
            preview = self.instance.get_preview_deadlines(
                attribute_data,
                subtype,
            )
        # Phase index 1 is always editable
        # Otherwise only current phase and upcoming phases are editable
        for phase in ProjectPhase.objects.filter(project_subtype=subtype) \
            .exclude(index__range=[2, min_phase_index-1]):
            sections_data += self.generate_sections_data(
                phase=phase,
                preview=preview,
                validation=should_validate,
            ) or []
            sections_data += self.generate_schedule_sections_data(
                phase=phase,
                validation=should_validate,
                preview=preview,
            ) or []

        sections_data += self.generate_floor_area_sections_data(
            floor_area_sections=ProjectFloorAreaSection.objects.filter(project_subtype=subtype),
            validation=should_validate,
            preview=preview,
        ) or []


        # To be able to validate the entire structure, we set the initial attributes
        # to the same as the already saved instance attributes.
        valid_attributes = {}
        if self.should_validate_attributes() and self.instance.attribute_data:
            # Make a deep copy of the attribute data if we are validating.
            # Can't assign straight since the values would be a reference
            # to the instance value. This will cause issues if attributes are
            # later removed while looping in the Project.update_attribute_data() method,
            # as it would mutate the dict while looping over it.
            valid_attributes = copy.deepcopy(self.instance.attribute_data)

        errors = {}
        for section_data in sections_data:
            # Get section serializer and validate input data against it
            serializer = section_data.serializer_class(data=attribute_data)
            if not serializer.is_valid(raise_exception=True):
                errors.update(serializer.errors)
            valid_attributes.update(serializer.validated_data)

        # If we should validate attribute data, then raise errors if they exist
        if self.should_validate_attributes() and errors:
            raise ValidationError(errors)

        # Confirmed deadlines can't be edited
        confirmed_deadlines = [
            dl.deadline.attribute.identifier for dl in self.instance.deadlines.all()
            if dl.confirmed and dl.deadline.attribute
        ] if self.instance else []

        if confirmed_deadlines:
            valid_attributes = {
                k: v for k, v in valid_attributes.items()
                if k not in confirmed_deadlines
            }

        invalid_identifiers = list(np.setdiff1d(
            list(attribute_data.keys()),
            list(valid_attributes.keys()),
        ))

        if len(invalid_identifiers):
            raise ValidationError(
                {
                    key: _("Cannot edit field.")
                    for key in invalid_identifiers
                }
            )

        if self.instance:
            for dl in ProjectDeadline.objects.filter(
                project=self.instance,
                deadline__attribute__identifier__in=valid_attributes.keys()
            ):
                dl.generated = False
                dl.save()

        return {**static_property_attributes, **valid_attributes}

    def _validate_public(self, attrs):
        public = attrs.get("public", True)

        # Do not validate if this is a new project
        if not self.instance and public is not None:
            return public
        elif not self.instance and public is None:
            return True

        # A project is always public if it has exited the starting phase
        try:
            phase_index = attrs["phase"].index
        except KeyError:
            phase_index = self.instance.phase.index

        if not self.instance.public and (phase_index > 1):
            return True

        return public

    def _validate_owner_edit_override(self, attrs):
        owner_edit_override = attrs.get("owner_edit_override", False)
        is_admin = self.context["request"].user.has_privilege("admin")

        if self.instance and is_admin:
            if owner_edit_override is None:
                return self.instance.owner_edit_override
            else:
                return owner_edit_override
        elif self.instance:
            return self.instance.owner_edit_override
        else:
            return False

    def validate_phase(self, phase, subtype_id=None):
        if not subtype_id:
            try:
                subtype_id = int(self.get_initial()["subtype"])
            except KeyError:
                subtype_id = self.instance.subtype.pk

        def _get_relative_phase(phase, offset):
            return phase.project_subtype.phases.get(index=phase.index + offset)

        offset = None

        # TODO hard-coded for now
        if phase.name == "Suunnitteluperiaatteet":
            if phase.project_subtype.pk == subtype_id:
                if not self.instance.create_principles:
                    offset = 1
            else:
                offset = -1

        if phase.name == "Luonnos":
            if phase.project_subtype.pk == subtype_id:
                if not self.instance.create_draft:
                    offset = 1
            else:
                offset = -2

        if offset:
            phase = _get_relative_phase(phase, offset)

        if phase.project_subtype.pk == subtype_id:
            return phase
        # Try to find a corresponding phase for current subtype
        else:
            try:
                return ProjectPhase.objects.get(name=phase.name, project_subtype__pk=subtype_id)
            except ProjectPhase.DoesNotExist:
                pass
            try:
                return ProjectPhase.objects.get(index=phase.index, project_subtype__pk=subtype_id)
            except ProjectPhase.DoesNotExist:
                raise ValidationError(
                    {"phase": _("Invalid phase for project subtype, no substitute found")}
                )

    def _validate_phase(self, attrs):
        try:
            return attrs["phase"]
        except KeyError:
            return self.validate_phase(
                ProjectPhase.objects.get(pk=self.instance.phase.pk),
                subtype_id=attrs["subtype"].id
            )

    def validate_user(self, user):
        if not user.has_privilege('create'):
            raise ValidationError(
                {"user": _("Selected user does not have the required role")}
            )

        return user

    def create(self, validated_data: dict) -> Project:
        validated_data["phase"] = ProjectPhase.objects.filter(
            project_subtype=validated_data["subtype"]
        ).first()

        with transaction.atomic():
            attribute_data = validated_data.pop("attribute_data", {})
            project: Project = super().create(validated_data)
            self.log_updates_attribute_data(attribute_data, project)

            # Update attribute data after saving the initial creation has
            # taken place so that there is no need to rewrite the entire
            # create function, even if the `update_attribute_data())` method
            # only sets values and does not make a `save()` call
            if attribute_data:
                project.update_attribute_data(attribute_data)
                project.save()

            user=self.context["request"].user
            project.update_deadlines(user=user)
            for dl in project.deadlines.all():
                self.create_deadline_updates_log(
                    dl.deadline, project, user, None, dl.date
                )

        return project

    def update(self, instance: Project, validated_data: dict) -> Project:
        attribute_data = validated_data.pop("attribute_data", {})
        subtype = validated_data.get("subtype")
        subtype_changed = subtype is not None and subtype != instance.subtype
        phase = validated_data.get("phase")
        phase_changed = phase is not None and phase != instance.phase
        should_generate_deadlines = getattr(
            self.context["request"], "GET", {}
        ).get("generate_schedule") in ["1", "true", "True"]
        user=self.context["request"].user

        if phase_changed:
            ProjectPhaseLog.objects.create(
                project=instance,
                phase=phase,
                user=user,
            )

        should_update_deadlines = self._get_should_update_deadlines(
            subtype_changed, instance, attribute_data,
        )

        with transaction.atomic():
            self.log_updates_attribute_data(attribute_data)
            if attribute_data:
                instance.update_attribute_data(attribute_data)

            project = super(ProjectSerializer, self).update(instance, validated_data)
            old_deadlines = project.deadlines.all()
            if should_generate_deadlines:
                cleared_attributes = {
                    project_dl.deadline.attribute.identifier: None
                    for project_dl in project.deadlines.all()
                    if project_dl.deadline.attribute
                }
                instance.update_attribute_data(cleared_attributes)
                self.log_updates_attribute_data(cleared_attributes)
                project.deadlines.all().delete()
                project.update_deadlines(user=user)
            elif should_update_deadlines:
                project.update_deadlines(user=user)

            project.save()

            updated_deadlines = old_deadlines.union(project.deadlines.all())
            for dl in updated_deadlines:
                try:
                    new_date = project.deadlines.get(deadline=dl.deadline).date
                except ProjectDeadline.DoesNotExist:
                    new_date = None

                try:
                    old_date = old_deadlines.get(deadline=dl.deadline).date
                except ProjectDeadline.DoesNotExist:
                    old_date = None

                self.create_deadline_updates_log(
                    dl.deadline, project, user, old_date, new_date
                )

            return project

    def log_updates_attribute_data(self, attribute_data, project=None):
        project = project or self.instance
        if not project:
            raise ValueError("Can't update attribute data log if no project")

        user = self.context["request"].user
        instance_attribute_date = getattr(self.instance, "attribute_data", {})
        updated_attribute_values = {}

        for identifier, value in attribute_data.items():
            existing_value = instance_attribute_date.get(identifier, None)

            if not value and not existing_value:
                old_file = ProjectAttributeFile.objects \
                    .filter(
                        project=project,
                        archived_at=None,
                        attribute__identifier=identifier,
                    ).order_by("-created_at").first()
                if old_file:
                    existing_value = old_file.description

            if value != existing_value:
                updated_attribute_values[identifier] = {
                    "old": existing_value,
                    "new": value,
                }

        updated_attributes = Attribute.objects.filter(
            identifier__in=updated_attribute_values.keys()
        )

        geometry_attributes = []
        for attribute in updated_attributes:
            # Add additional checks for geometries since they are not actually stored
            # in the attribute_data but in their own model
            if attribute.value_type == Attribute.TYPE_GEOMETRY:
                geometry_attributes.append(attribute)
                continue

            values = updated_attribute_values[attribute.identifier]

            if attribute.value_type == Attribute.TYPE_CHOICE:
                if isinstance(values["new"], list):
                    values["new"] = [
                        value.identifier for value in values["new"]
                    ]
                else:
                    try:
                        values["new"] = values["new"].identifier
                    except AttributeError:
                        pass

            self._create_updates_log(
                attribute, project, user, values["new"], values["old"]
            )

        for geometry_attribute in geometry_attributes:
            geometry_instance = ProjectAttributeMultipolygonGeometry.objects.filter(
                project=project, attribute=geometry_attribute
            ).first()
            new_geometry = attribute_data[geometry_attribute.identifier]
            if geometry_instance and geometry_instance.geometry != new_geometry:
                self._create_updates_log(geometry_attribute, project, user, None, None)

    def _create_updates_log(self, attribute, project, user, new_value, old_value):
        new_value = json.loads(json.dumps(new_value, default=str))
        old_value = json.loads(json.dumps(old_value, default=str))
        entry = action.send(
            user,
            verb=verbs.UPDATED_ATTRIBUTE,
            action_object=attribute,
            target=project,
            attribute_identifier=attribute.identifier,
            old_value=old_value,
            new_value=new_value,
        )
        if attribute.broadcast_changes:
            if not old_value and not new_value:
                change_string = ""
            else:
                old_value = old_value or "<tyhjä>"
                new_value = new_value or "<tyhjä>"
                change_string = f"\n{old_value} -> {new_value}"
            ProjectComment.objects.create(
                project=project,
                generated=True,
                content=f'{user.get_display_name()} päivitti "{attribute.name}" tietoa.{change_string}',
            )

        if attribute.value_type in [Attribute.TYPE_FILE, Attribute.TYPE_IMAGE] \
            and new_value is None:
            timestamp = entry[0][1].timestamp
            for old_file in ProjectAttributeFile.objects.filter(
                project=project,
                attribute=attribute,
                archived_at=None,
            ):
                old_file.archived_at = timestamp
                old_file.save()

    def create_deadline_updates_log(self, deadline, project, user, old_date, new_date):
        old_value = json.loads(json.dumps(old_date, default=str))
        new_value = json.loads(json.dumps(new_date, default=str))

        if old_value != new_value:
            action.send(
                user,
                verb=verbs.UPDATED_DEADLINE,
                action_object=deadline,
                target=project,
                deadline_abbreviation=deadline.abbreviation,
                old_value=old_value,
                new_value=new_value,
            )


class ProjectSnapshotSerializer(ProjectSerializer):
    user = serializers.SerializerMethodField()
    name = serializers.SerializerMethodField()
    pino_number = serializers.SerializerMethodField()
    create_principles = serializers.SerializerMethodField()
    create_draft = serializers.SerializerMethodField()
    subtype = serializers.SerializerMethodField()
    phase = serializers.SerializerMethodField()

    class Meta:
        model = Project
        fields = [
            "user",
            "created_at",
            "modified_at",
            "name",
            "identifier",
            "pino_number",
            "type",
            "subtype",
            "attribute_data",
            "phase",
            "id",
            "deadlines",
            "create_principles",
            "create_draft",
            "_metadata",
        ]
        read_only_fields = fields

    def _get_static_property(self, project, static_property):
        attribute_data = self.get_attribute_data(project)
        try:
            identifier = \
                Attribute.objects.get(static_property=static_property).identifier
            return attribute_data[identifier]
        except (Attribute.DoesNotExist, KeyError):
            return getattr(project, static_property)

    def get_user(self, project):
        return self._get_static_property(project, "user").uuid

    def get_name(self, project):
        return self._get_static_property(project, "name")

    def get_pino_number(self, project):
        return self._get_static_property(project, "pino_number")

    def get_create_principles(self, project):
        return self._get_static_property(project, "create_principles")

    def get_create_draft(self, project):
        return self._get_static_property(project, "create_draft")

    def get_subtype(self, project):
        try:
            return ProjectPhaseLog.objects.filter(
                created_at__lte=self._get_snapshot_date(project),
                project=project
            ).order_by("-created_at").first().phase.project_subtype.id
        except (ProjectPhaseLog.DoesNotExist, AttributeError):
            return project.subtype.id

    def get_phase(self, project):
        try:
            return ProjectPhaseLog.objects.filter(
                created_at__lte=self._get_snapshot_date(project),
                project=project
            ).order_by("-created_at").first().phase.id
        except (ProjectPhaseLog.DoesNotExist, AttributeError):
            return project.phase.id

    def get_deadlines(self, project):
        snapshot = self._get_snapshot_date(project)

        actions = (
            project.target_actions.filter(
                verb=verbs.UPDATED_DEADLINE,
                timestamp__lte=snapshot,
            )
            .order_by(
                "action_object_content_type", "action_object_object_id", "-timestamp"
            )
            .distinct("action_object_content_type", "action_object_object_id")
            .prefetch_related("actor")
        )

        return [
            {
                "date": _action.data.get("new_value"),
                "abbreviation": _action.data.get("deadline_abbreviation")
            }
            for _action in actions
            if _action.data.get("new_value") is not None
        ]


class AdminProjectSerializer(ProjectSerializer):
    def get_fields(self):
        fields = super(AdminProjectSerializer, self).get_fields()
        request = self.context.get('request', None)

        fields["archived"] = serializers.NullBooleanField(required=False)
        fields["public"] = serializers.NullBooleanField(required=False)
        fields["owner_edit_override"] = serializers.NullBooleanField(required=False)
        fields["onhold"] = serializers.NullBooleanField(required=False)

        return fields


class ProjectPhaseSerializer(serializers.ModelSerializer):
    project_type = serializers.SerializerMethodField()

    class Meta:
        model = ProjectPhase
        fields = [
            "id",
            "project_type",
            "project_subtype",
            "name",
            "color",
            "color_code",
            "list_prefix",
            "index",
        ]

    def get_project_type(self, project):
        return project.project_type.pk


class FieldsetPathField(serializers.JSONField):
    def to_representation(self, value):
        return [
            {
                "parent": i["parent"].identifier,
                "index": i["index"],
            }
            for i in value
        ]


class ProjectFileSerializer(serializers.ModelSerializer):
    file = serializers.FileField(use_url=True)
    attribute = serializers.SlugRelatedField(
        slug_field="identifier",
        queryset=Attribute.objects.filter(
            value_type__in=[Attribute.TYPE_IMAGE, Attribute.TYPE_FILE]
        ),
    )
    project = serializers.PrimaryKeyRelatedField(queryset=Project.objects.all())
    fieldset_path = FieldsetPathField(binary=True, required=False)

    class Meta:
        model = ProjectAttributeFile
        fields = ["file", "attribute", "project", "description", "fieldset_path"]

    @staticmethod
    def _validate_attribute(attribute: Attribute, project: Project):
        # Check if the attribute is part of the project
        try:
            # Field belongs to a fieldset
            project_has_attribute = bool(ProjectPhaseSectionAttribute.objects.filter(
                section__phase__project_subtype__project_type=project.type,
                attribute=attribute.fieldset_attribute_target.get().attribute_source,
            ).count)
        except ObjectDoesNotExist:
            project_has_attribute = bool(ProjectPhaseSectionAttribute.objects.filter(
                section__phase__project_subtype__project_type=project.type,
                attribute=attribute,
            ).count())

        if not project_has_attribute:
            # Using the same error message as SlugRelatedField
            raise ValidationError(_("Object with {slug_name}={value} does not exist."))

    def validate(self, attrs: dict):
        self._validate_attribute(attrs["attribute"], attrs["project"])

        return attrs

    def create(self, validated_data):
        fieldset_path = validated_data.pop("fieldset_path", [])
        attribute = validated_data["attribute"]

        # Save new path as a string for easier querying
        if fieldset_path:
            path_string = ".".join([
                f"{loc['parent']}[{loc['index']}]"
                for loc in fieldset_path
            ]) + f".{attribute.identifier}"
            validated_data["fieldset_path_str"] = path_string

        else:
            path_string = None

        old_files = ProjectAttributeFile.objects.filter(
            project=validated_data["project"],
            attribute=attribute,
            archived_at=None,
            fieldset_path_str=path_string,
        ).order_by("-created_at")

        try:
            old_file = old_files[0]
            old_value = old_file.description
        except (AttributeError, IndexError):
            old_file = None
            old_value = None

        new_file = super().create(validated_data)
        new_value = new_file.description

        # Create related fieldset path objects
        for i, location in enumerate(fieldset_path):
            ProjectAttributeFileFieldsetPathLocation.objects.create(
                target=new_file,
                index=i,
                child_index=location["index"],
                parent_fieldset=Attribute.objects.get(
                    identifier=location["parent"],
                ),
            )

        if old_value != new_value or old_file and old_file.file != new_file.file:
            log_identifier = \
                path_string or \
                validated_data["attribute"].identifier
            entry = action.send(
                self.context["request"].user or validated_data["project"].user,
                verb=verbs.UPDATED_ATTRIBUTE,
                action_object=attribute,
                target=validated_data["project"],
                attribute_identifier=log_identifier,
                new_value=new_value,
                old_value=old_value,
            )
            timestamp = entry[0][1].timestamp
        else:
            timestamp = datetime.datetime.now()

        for old_file in old_files:
            old_file.archived_at = timestamp
            old_file.save()

        return new_file
