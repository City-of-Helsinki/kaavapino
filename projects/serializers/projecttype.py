from django.db.models import Case, When
from rest_framework import serializers

from projects.models import ProjectType, ProjectSubtype, Attribute


class ProjectSubtypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProjectSubtype
        fields = ["id", "name", "metadata", "project_type"]


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

        # Order for qs, taken from https://stackoverflow.com/a/38390480
        # Note: Ordering like this is not recommended for larger sets since
        # the query gets mighty long, but we will never have more then a few
        # tens of fields here which should not cause any performance degradation.
        # Note2: This can also be done by convering to a list and order that
        # according to another list, but then the a QuerySet would not longer
        # exist.
        identifier_ordering = Case(
            *[
                When(identifier=identifier, then=pos)
                for pos, identifier in enumerate(attribute_identifiers)
            ]
        )
        attributes = Attribute.objects.filter(
            identifier__in=attribute_identifiers
        ).order_by(identifier_ordering)
        return ProjectTypeMetadataCardAttributeSerializer(attributes, many=True).data


class ProjectTypeSerializer(serializers.ModelSerializer):
    metadata = ProjectTypeMetadataSerializer()
    subtypes = ProjectSubtypeSerializer(many=True)

    class Meta:
        model = ProjectType
        fields = ["id", "name", "metadata", "subtypes"]
