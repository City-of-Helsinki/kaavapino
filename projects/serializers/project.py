import copy
from typing import List, NamedTuple, Type

from actstream import action
from django.contrib.auth import get_user_model
from django.core.exceptions import ObjectDoesNotExist
from django.db import transaction
from django.db.models import Prefetch
from django.utils.translation import ugettext_lazy as _
from rest_framework import serializers
from rest_framework.exceptions import ValidationError
from rest_framework.serializers import Serializer
from rest_framework_gis.fields import GeometryField

from projects.actions import verbs
from projects.models import (
    Project,
    ProjectSubtype,
    ProjectPhase,
    ProjectPhaseSection,
    ProjectFloorAreaSection,
    ProjectAttributeFile,
    Attribute,
    ProjectPhaseSectionAttribute,
    ProjectComment,
)
from projects.models.project import ProjectAttributeMultipolygonGeometry
from projects.permissions.media_file_permissions import (
    has_project_attribute_file_permissions,
)
from projects.serializers.fields import AttributeDataField
from projects.serializers.section import create_section_serializer
from users.models import User
from users.serializers import UserSerializer


class SectionData(NamedTuple):
    section: ProjectPhaseSection
    serializer_class: Type[Serializer]


class ProjectDeadlinesSerializer(serializers.Serializer):
    phase_id = serializers.IntegerField(required=True)
    phase_name = serializers.CharField(read_only=True)
    start = serializers.DateTimeField()
    deadline = serializers.DateTimeField(required=True)


class ProjectSerializer(serializers.ModelSerializer):
    user = serializers.SlugRelatedField(
        read_only=False, slug_field="uuid", queryset=get_user_model().objects.all()
    )
    attribute_data = AttributeDataField(allow_null=True, required=False)
    type = serializers.SerializerMethodField()
    deadlines = ProjectDeadlinesSerializer(many=True, allow_null=True, required=False)
    public = serializers.NullBooleanField(required=False, read_only=True)
    archived = serializers.NullBooleanField(required=False, read_only=True)
    onhold = serializers.NullBooleanField(required=False, read_only=True)

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
            "archived",
            "onhold",
            "deadlines",
            "create_principles",
            "create_draft",
            "_metadata",
        ]
        read_only_fields = ["type", "created_at", "modified_at"]

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
        attribute_data = getattr(project, "attribute_data", {})
        self._set_file_attributes(attribute_data, project)
        self._set_geometry_attributes(attribute_data, project)

        return attribute_data

    def get_type(self, project):
        return project.type.pk

    def _set_file_attributes(self, attribute_data, project):
        request = self.context["request"]
        attribute_files = ProjectAttributeFile.objects.filter(project=project)

        # Add file attributes to the attribute data
        # File values are represented as absolute URLs
        file_attributes = {
            attribute_file.attribute.identifier: {
                "link": request.build_absolute_uri(attribute_file.file.url),
                "description": attribute_file.description,
            }
            for attribute_file in attribute_files
            if has_project_attribute_file_permissions(attribute_file, request)
        }
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
        if not list_view:
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
    def _get_updates(project):
        # Get the latest attribute updates for distinct attributes
        actions = (
            project.target_actions.filter(verb=verbs.UPDATED_ATTRIBUTE)
            .order_by(
                "action_object_content_type", "action_object_object_id", "-timestamp"
            )
            .distinct("action_object_content_type", "action_object_object_id")
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
        self, phase: ProjectPhase, validation: bool = True
    ) -> List[SectionData]:
        sections = []
        for section in phase.sections.order_by("index"):
            serializer_class = create_section_serializer(
                section,
                context=self.context,
                project=self.instance,
                validation=validation,
            )
            section_data = SectionData(section, serializer_class)
            sections.append(section_data)

        return sections

    def generate_floor_area_sections_data(
        self, floor_area_sections, validation: bool = True
    ) -> List[SectionData]:
        sections = []
        for section in floor_area_sections.order_by("index"):
            serializer_class = create_section_serializer(
                section,
                context=self.context,
                project=self.instance,
                validation=validation,
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

        attrs["attribute_data"] = self._validate_attribute_data(
            attrs.get("attribute_data", None), attrs
        )

        deadlines = self._validate_deadlines(attrs)
        public = self._validate_public(attrs)

        if public:
            attrs["public"] = public

        if deadlines:
            attrs["deadlines"] = deadlines

        return attrs

    def _validate_attribute_data(self, attribute_data, validate_attributes):
        # Get serializers for all sections in all phases
        sections_data = []
        current_phase = getattr(self.instance, "phase", None)
        subtype = getattr(self.instance, "subtype", None) or \
            validate_attributes.get("subtype")
            # TODO: check if this subtype should be an attribute of phase object instead
            #validate_attributes.get("phase").project_subtype
        should_validate = self.should_validate_attributes()
        max_phase_index = current_phase.index if current_phase else 1
        if not should_validate:
            max_phase_index = (
                ProjectPhase.objects.filter(project_subtype=subtype)
                .order_by("-index")
                .values_list("index", flat=True)
                .first()
            ) or max_phase_index
        for phase in ProjectPhase.objects.filter(
            index__lte=max_phase_index, project_subtype=subtype
        ):
            sections_data += self.generate_sections_data(
                phase=phase, validation=self.should_validate_attributes()
            )

        sections_data += self.generate_floor_area_sections_data(
            floor_area_sections=ProjectFloorAreaSection.objects.filter(project_subtype=subtype),
            validation=self.should_validate_attributes()
        )

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
            if not serializer.is_valid():
                errors.update(serializer.errors)
            valid_attributes.update(serializer.validated_data)

        # If we should validate attribute data, then raise errors if they exist
        if self.should_validate_attributes() and errors:
            raise ValidationError(errors)

        return valid_attributes

    def _validate_public(self, attrs):
        public = attrs.get("public", True)

        # Do not validate if this is a new project
        if public is None or not self.instance:
            return public

        # A project is always public if it has exited the starting phase
        try:
            phase_index = attrs["phase"]
        except KeyError:
            phase_index = self.instance.phase.index

        if not self.instance.public and (phase_index > 0):
            return True

        return public

    def validate_phase(self, phase):
        def _get_next_phase(phase):
            return phase.project_subtype.phases.get(pk=phase.index + 1)

        # TODO hard-coded for now
        if phase.name == "Suunnitteluperiaatteet" and not self.instance.create_principles:
            phase = _get_next_phase(phase)

        if phase.name == "Luonnos" and not self.instance.create_draft:
            phase = _get_next_phase(phase)

        try:
            subtype_id = int(self.get_initial()["subtype"])
        except KeyError:
            subtype_id = self.instance.subtype.pk

        if phase.project_subtype.pk == subtype_id:
            return phase
        # Try to find a corresponding phase for current subtype
        else:
            try:
                return ProjectPhase.objects.get(name=phase.name, project_subtype__pk=subtype_id)
            except ProjectPhase.DoesNotExist:
                raise ValidationError(
                    {"phase": _("Invalid phase for project subtype")}
                )

    def validate_user(self, user):
        if not user.has_privilege('create'):
            raise ValidationError(
                {"user": _("Selected user does not have the required role")}
            )

        return user

    def _validate_deadlines(self, attrs):
        """
        Validates that deadlines values are correct

        - Only the first start date can be changed
        - There can be no overlapping deadlines
        - All phases in a project needs to be set at once
        - The same phase can not be defined more than one time
        """

        deadlines = attrs.get("deadlines", None)
        if not deadlines:
            return None
        # Sort the deadlines in-place by phase
        deadlines.sort(key=lambda _deadline: _deadline["phase_id"])

        project = self.instance

        # If there is no project then any value sent in will not
        # matter since the model will set default deadlines values
        # and override anything sent in
        if not project:
            return deadlines

        validated_phase_ids = []
        latest_deadline = deadlines[0]["deadline"]

        # Make sure that all phases are included in the deadlines
        required_project_phase_ids = list(
            ProjectPhase.objects.filter(project_subtype=project.subtype)
            .order_by("id")
            .values_list("id", flat=True)
        )
        attribute_phase_ids = [deadline["phase_id"] for deadline in deadlines]
        if not required_project_phase_ids == attribute_phase_ids:
            raise ValidationError(
                {
                    "deadlines": _(
                        "All phases for the sub type needs to be included in the deadlines list"
                    )
                }
            )

        for idx, deadline in enumerate(deadlines):
            if latest_deadline > deadline["deadline"]:
                raise ValidationError(
                    {
                        "deadlines": _(
                            'Invalid date "{deadline}", must be after "{latest_deadline}"'.format(
                                deadline=deadline["deadline"],
                                latest_deadline=latest_deadline,
                            )
                        )
                    }
                )

            phase_id = deadline["phase_id"]
            if phase_id in validated_phase_ids:
                raise ValidationError(
                    {
                        "deadlines": _(
                            'Multiple pk value "{pk_value}"'.format(pk_value=phase_id)
                        )
                    }
                )

            try:
                phase = ProjectPhase.objects.get(
                    pk=phase_id, project_subtype=project.subtype
                )
            except ObjectDoesNotExist:
                raise ValidationError(
                    {
                        "deadlines": _(
                            'Invalid pk "{pk_value}" - object does not exist.'.format(
                                pk_value=phase_id
                            )
                        )
                    }
                )

            # Let the first start date be changed by the user
            # and set the rest of them depending on the previous
            # deadlines.
            if idx == 0:
                deadline["start"] = deadlines[0]["start"]
            else:
                deadline["start"] = latest_deadline
            deadline["phase_name"] = phase.name

            latest_deadline = deadline["deadline"]
            validated_phase_ids.append(phase_id)

        return deadlines

    def create(self, validated_data: dict) -> Project:
        validated_data["phase"] = ProjectPhase.objects.filter(
            project_subtype=validated_data["subtype"]
        ).first()

        deadlines = validated_data.pop("deadlines", [])

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

            if deadlines:
                project.deadlines = deadlines
                project.save()
            else:
                project.set_default_deadlines()

        return project

    def update(self, instance: Project, validated_data: dict) -> Project:
        attribute_data = validated_data.pop("attribute_data", {})
        deadlines = validated_data.pop("deadlines", None)
        with transaction.atomic():
            self.log_updates_attribute_data(attribute_data)
            if attribute_data:
                instance.update_attribute_data(attribute_data)

            project = super(ProjectSerializer, self).update(instance, validated_data)
            if deadlines:
                project.deadlines = deadlines
            project.save()
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
                    values["new"] = values["new"].identifier

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
        action.send(
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


class AdminProjectSerializer(ProjectSerializer):
    def get_fields(self):
        fields = super(AdminProjectSerializer, self).get_fields()
        request = self.context.get('request', None)

        fields["archived"] = serializers.NullBooleanField(required=False)
        fields["public"] = serializers.NullBooleanField(required=False)
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
            "index",
        ]

    def get_project_type(self, project):
        return project.project_type.pk


class ProjectFileSerializer(serializers.ModelSerializer):
    file = serializers.FileField(use_url=True)
    attribute = serializers.SlugRelatedField(
        slug_field="identifier",
        queryset=Attribute.objects.filter(
            value_type__in=[Attribute.TYPE_IMAGE, Attribute.TYPE_FILE]
        ),
    )
    project = serializers.PrimaryKeyRelatedField(queryset=Project.objects.all())

    class Meta:
        model = ProjectAttributeFile
        fields = ["file", "attribute", "project", "description"]

    @staticmethod
    def _validate_attribute(attribute: Attribute, project: Project):
        # Check if the attribute is part of the project
        project_has_attribute = bool(
            ProjectPhaseSectionAttribute.objects.filter(
                section__phase__project_subtype__project_type=project.type,
                attribute=attribute,
            ).count()
        )
        if not project_has_attribute:
            # Using the same error message as SlugRelatedField
            raise ValidationError(_("Object with {slug_name}={value} does not exist."))

    def validate(self, attrs: dict):
        self._validate_attribute(attrs["attribute"], attrs["project"])

        return attrs
