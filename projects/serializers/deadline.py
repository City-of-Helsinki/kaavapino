from drf_spectacular.utils import extend_schema_field
from drf_spectacular.types import OpenApiTypes
from rest_framework import serializers

from projects.models import Deadline


class DeadlineSerializer(serializers.Serializer):
    abbreviation = serializers.CharField()
    attribute = serializers.SerializerMethodField()
    deadline_types = serializers.ListField(
        child=serializers.CharField()
    )
    date_type = serializers.CharField()
    phase_id = serializers.IntegerField(source="phase.pk")
    phase_name = serializers.CharField(source="phase.name")
    phase_color = serializers.CharField(source="phase.color")
    phase_color_code = serializers.CharField(source="phase.color_code")
    index = serializers.IntegerField()
    error_past_due = serializers.CharField()
    error_date_type_mismatch = serializers.CharField()
    error_min_distance_previous = serializers.CharField()
    warning_min_distance_next = serializers.CharField()
    deadlinegroup = serializers.CharField()

    @extend_schema_field(OpenApiTypes.STR)
    def get_attribute(self, deadline):
        if deadline.attribute:
            return deadline.attribute.identifier
        else:
            return None


class DateTypeSerializer(serializers.Serializer):
    identifier = serializers.CharField()
    name = serializers.CharField()
    dates = serializers.ListField(
        child=serializers.DateField(), allow_null=False, allow_empty=False
    )


class DeadlineValidDateSerializer(serializers.Serializer):
    date_types = serializers.DictField(child=DateTypeSerializer(), allow_null=False, allow_empty=False)


class DeadlineValidationSerializer(serializers.Serializer):
    identifier = serializers.CharField()
    project = serializers.CharField()
    date = serializers.CharField()
    error_reason = serializers.CharField()
    suggested_date = serializers.DateField()
    conflicting_deadline = serializers.CharField()
    conflicting_deadline_abbreviation = serializers.CharField()
