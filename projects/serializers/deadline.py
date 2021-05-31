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

    def get_attribute(self, deadline):
        if deadline.attribute:
            return deadline.attribute.identifier
        else:
            return None
