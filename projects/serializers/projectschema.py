from django.contrib.auth import get_user_model
from rest_framework import serializers

from projects.models import Attribute
from projects.serializers.utils import _is_attribute_required


VALUE_TYPE_MAP = {Attribute.TYPE_USER: Attribute.TYPE_SHORT_STRING}

FOREIGN_KEY_TYPE_MODELS = {
    Attribute.TYPE_USER: {
        "model": get_user_model(),
        "filters": {},
        "label_format": "{instance.first_name} {instance.last_name}",
    }
}


class ProjectAttributeChoiceSchemaSerializer(serializers.Serializer):
    label = serializers.CharField()
    value = serializers.CharField()


class ProjectSectionAttributeSchemaSerializer(serializers.Serializer):
    label = serializers.CharField(source="attribute.name")
    name = serializers.CharField(source="attribute.identifier")
    help_text = serializers.CharField(source="attribute.help_text")
    multiple_choice = serializers.BooleanField(source="attribute.multiple_choice")
    relies_on = serializers.CharField(
        source="relies_on.attribute.identifier", allow_null=True
    )
    type = serializers.SerializerMethodField()
    required = serializers.SerializerMethodField()
    choices = serializers.SerializerMethodField()

    @staticmethod
    def get_required(section_attribute):
        return _is_attribute_required(section_attribute)

    @staticmethod
    def get_type(section_attribute):
        value_type = section_attribute.attribute.value_type
        # Remap values if applicable
        return VALUE_TYPE_MAP.get(value_type, value_type)

    @staticmethod
    def get_choices(section_attribute):
        foreign_key_choice = FOREIGN_KEY_TYPE_MODELS.get(
            section_attribute.attribute.value_type, None
        )

        if foreign_key_choice:
            choices = ProjectSectionAttributeSchemaSerializer._get_foreign_key_choices(
                foreign_key_choice
            )
        else:
            choices = ProjectSectionAttributeSchemaSerializer._get_section_attribute_choices(
                section_attribute
            )

        if not choices:
            return None

        return ProjectAttributeChoiceSchemaSerializer(choices, many=True).data

    @staticmethod
    def _get_foreign_key_choices(choice_data):
        choices = []
        model = choice_data["model"]
        filters = choice_data["filters"]
        label_format = choice_data["label_format"]
        choice_instances = model.objects.filter(**filters)
        for choice in choice_instances:
            choices.append(
                {"label": label_format.format(instance=choice), "value": choice.pk}
            )
        return choices

    @staticmethod
    def _get_section_attribute_choices(section_attribute):
        choices = []
        choice_instances = section_attribute.attribute.value_choices.all()
        for choice in choice_instances:
            choices.append({"label": choice.value, "value": choice.identifier})
        return choices


class ProjectSectionSchemaSerializer(serializers.Serializer):
    title = serializers.CharField(source="name")
    fields = ProjectSectionAttributeSchemaSerializer(
        source="projectphasesectionattribute_set", many=True
    )


class ProjectPhaseSchemaSerializer(serializers.Serializer):
    title = serializers.CharField(source="name")
    color = serializers.CharField()
    color_code = serializers.CharField()
    sections = ProjectSectionSchemaSerializer(many=True)


class ProjectTypeSchemaSerializer(serializers.Serializer):
    title = serializers.CharField(source="name")
    phases = ProjectPhaseSchemaSerializer(many=True)
