from rest_framework import serializers

from projects.models import ProjectType, Attribute


class ProjectTypeMetadataCardAttributeSerializer(serializers.ModelSerializer):
    name = serializers.CharField(source="identifier")
    label = serializers.CharField(source="name")
    type = serializers.CharField(source="value_type")

    class Meta:
        fields = ["name", "label", "type"]
        model = Attribute


class ProjectTypeMetadataSerializer(serializers.Serializer):
    normal_project_card_attributes = serializers.SerializerMethodField()
    extended_project_card_attributes = serializers.SerializerMethodField()

    def get_normal_project_card_attributes(self, metadata):
        return self._get_card_attributes(metadata, "normal_project_card_attributes")

    def get_extended_project_card_attributes(self, metadata):
        return self._get_card_attributes(metadata, "extended_project_card_attributes")

    def _get_card_attributes(self, metadata, field):
        attribute_identifiers = metadata.get(field, [])
        if not attribute_identifiers:
            return attribute_identifiers

        attributes = Attribute.objects.filter(identifier__in=attribute_identifiers)
        return ProjectTypeMetadataCardAttributeSerializer(attributes, many=True).data


class ProjectTypeSerializer(serializers.ModelSerializer):
    metadata = ProjectTypeMetadataSerializer()

    class Meta:
        model = ProjectType
        fields = ["id", "name", "metadata"]
