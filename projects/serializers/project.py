import copy
from typing import List, NamedTuple, Type

from actstream import action
from django.contrib.auth import get_user_model
from django.db import transaction
from rest_framework import serializers
from rest_framework.exceptions import ValidationError
from rest_framework.serializers import Serializer

from django.utils.translation import ugettext_lazy as _

from projects import validators
from projects.models import (
    Project,
    ProjectPhase,
    ProjectPhaseSection,
    ProjectAttributeFile,
    Attribute,
    ProjectPhaseSectionAttribute,
)
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


class ProjectSerializer(serializers.ModelSerializer):
    user = serializers.SlugRelatedField(
        read_only=False, slug_field="uuid", queryset=get_user_model().objects.all()
    )
    attribute_data = AttributeDataField(allow_null=True, required=False)
    type = serializers.SerializerMethodField()

    _metadata = serializers.SerializerMethodField()

    class Meta:
        model = Project
        fields = [
            "user",
            "created_at",
            "modified_at",
            "name",
            "identifier",
            "type",
            "subtype",
            "attribute_data",
            "phase",
            "geometry",
            "id",
            "public",
            "_metadata",
        ]
        read_only_fields = ["type", "created_at", "modified_at"]

    def get_attribute_data(self, project):
        attribute_data = getattr(project, "attribute_data", {})
        self._set_file_attributes(attribute_data, project)

        return attribute_data

    def get_type(self, project):
        return project.type.pk

    def _set_file_attributes(self, attribute_data, project):
        request = self.context["request"]
        attribute_files = ProjectAttributeFile.objects.filter(project=project)

        # Add file attributes to the attribute data
        # File values are represented as absolute URLs
        file_attributes = {
            attribute_file.attribute.identifier: request.build_absolute_uri(
                attribute_file.file.url
            )
            for attribute_file in attribute_files
            if has_project_attribute_file_permissions(attribute_file, request)
        }
        attribute_data.update(file_attributes)

    def get__metadata(self, project):
        list_view = self.context.get("action", None) == "list"
        return {"users": self._get_users(project, list_view=list_view)}

    @staticmethod
    def _get_users(project, list_view=False):
        users = [project.user]

        if not list_view:
            attributes = Attribute.objects.filter(
                value_type=Attribute.TYPE_USER
            ).values_list("identifier", flat=True)
            user_attribute_ids = []
            for attribute in attributes:
                user_id = project.attribute_data.get(attribute, None)
                if user_id:
                    user_attribute_ids.append(user_id)

            users += list(User.objects.filter(uuid__in=user_attribute_ids))

        return UserSerializer(users, many=True).data

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

    def validate_attribute_data(self, attribute_data):
        # Get serializers for all sections in all phases
        sections_data = []
        current_phase = getattr(self.instance, "phase", None)
        current_phase_index = current_phase.index if current_phase else 1
        for phase in ProjectPhase.objects.filter(
            project_subtype__project_type__name="asemakaava",
            index__lte=current_phase_index,
        ):
            sections_data += self.generate_sections_data(
                phase=phase, validation=self.should_validate_attributes()
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

    def validate_public(self, public):
        # Do not validate if this is a new project or
        # the value did not change.
        if not self.instance or public == self.instance.public:
            return public

        request = self.context["request"]
        user_is_request_user = self.instance.user == request.user
        if not user_is_request_user and not request.user.is_superuser:
            raise ValidationError(_("You do not have permissions to change this value"))

        return public

    def validate_phase(self, phase):
        user = self.context["request"].user
        is_responsible = user == self.instance.user

        if is_responsible:
            return phase

        return validators.admin_or_read_only(
            phase, "phase", self.instance, self.context
        )

    def validate_user(self, user):
        if not self.instance:
            return user
        return validators.admin_or_read_only(user, "user", self.instance, self.context)

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

        return project

    def update(self, instance: Project, validated_data: dict) -> Project:
        attribute_data = validated_data.pop("attribute_data", {})
        with transaction.atomic():
            self.log_updates_attribute_data(attribute_data)
            if attribute_data:
                instance.update_attribute_data(attribute_data)

            return super(ProjectSerializer, self).update(instance, validated_data)

    def log_updates_attribute_data(self, attribute_data, project=None):
        project = project or self.instance
        if not project:
            raise ValueError("Can't update attribute data log if no project")

        user = self.context["request"].user
        instance_attribute_date = getattr(self.instance, "attribute_data", {})
        updated_attribute_identifiers = []

        for identifier, value in attribute_data.items():
            existing_value = instance_attribute_date.get(identifier, None)
            if value != existing_value:
                updated_attribute_identifiers.append(identifier)

        updated_attributes = Attribute.objects.filter(
            identifier__in=updated_attribute_identifiers
        )
        for attribute in updated_attributes:
            action.send(
                user,
                verb="updated attribute",
                action_object=attribute,
                target=project,
                attribute_identifier=attribute.identifier,
            )


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
        fields = ["file", "attribute", "project"]

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
