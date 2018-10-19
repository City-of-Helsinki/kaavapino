import copy
from typing import List, NamedTuple, Type

from django.db import transaction
from rest_framework import serializers
from rest_framework.exceptions import ValidationError
from rest_framework.serializers import Serializer

from projects.models import Project, ProjectPhase, ProjectPhaseSection, ProjectType
from projects.serializers.section import create_section_serializer


class ProjectTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = Project
        fields = ["name"]


class SectionData(NamedTuple):
    section: ProjectPhaseSection
    serializer_class: Type[Serializer]


class ProjectSerializer(serializers.ModelSerializer):
    class Meta:
        model = Project
        fields = [
            "user",
            "created_at",
            "modified_at",
            "name",
            "identifier",
            "type",
            "attribute_data",
            "phase",
            "geometry",
            "id",
        ]
        read_only_fields = ["phase", "type", "created_at", "modified_at"]

    def should_validate_attributes(self):
        validate_field_data = self.context["request"].data.get(
            "validate_attribute_data", False
        )
        return serializers.BooleanField().to_internal_value(validate_field_data)

    def generate_sections_data(self, phase: ProjectPhase) -> List[SectionData]:
        sections = []
        for section in phase.sections.order_by("index"):
            serializer_class = create_section_serializer(section)
            section_data = SectionData(section, serializer_class)
            sections.append(section_data)

        return sections

    def validate_attribute_data(self, attribute_data):
        # Get instance phase or use the first phase for the project type
        phase = (
            self.instance.phase
            if self.instance and getattr(self.instance, "phase", None)
            else ProjectPhase.objects.get(project_type__name="asemakaava", index=0)
        )

        # Get serializers for all sections in the phase
        sections_data = self.generate_sections_data(phase=phase)

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

        errors = []
        for section_data in sections_data:
            # Get section serializer and validate input data against it
            serializer = section_data.serializer_class(data=attribute_data)
            if not serializer.is_valid():
                errors += serializer.errors

            valid_attributes.update(serializer.data)

        # If we should validate attribute data, then raise errors if they exist
        if self.should_validate_attributes() and errors:
            raise ValidationError(errors)

        return valid_attributes

    def create(self, validated_data: dict) -> Project:
        validated_data["phase"] = ProjectPhase.objects.get(
            project_type__name="asemakaava", index=0
        )
        validated_data["type"] = ProjectType.objects.first()

        with transaction.atomic():
            project: Project = super().create(validated_data)

            # Update attribute data after saving the initial creation has
            # taken place so that there is no need to rewrite the entire
            # create function, even if the `update_attribute_data())` method
            # only sets values and does not make a `save()` call
            attribute_data = validated_data.pop("attribute_data", {})
            if attribute_data:
                project.update_attribute_data(attribute_data)
                project.save()

        return project

    def update(self, instance: Project, validated_data: dict) -> Project:
        attribute_data = validated_data.pop("attribute_data", {})
        if attribute_data:
            instance.update_attribute_data(attribute_data)

        return super(ProjectSerializer, self).update(instance, validated_data)
