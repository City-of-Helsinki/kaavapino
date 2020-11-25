from rest_framework import serializers

from projects.models import Deadline


class DeadlineSerializer(serializers.Serializer):
    abbreviation = serializers.CharField()
    attribute_identifier = serializers.CharField(source="attribute.identifier")
    editable = serializers.SerializerMethodField()
    deadline_types = serializers.ListField(
        serializers.CharField()
    )
    date_type = serializers.IntegerField()
    error_past_due = serializers.CharField()
    phase_id = serializers.IntegerField(source="phase.pk")
    phase_name = serializers.CharField(source="phase.name")
    phase_color = serializers.CharField(source="phase.color")
    phase_color_code = serializers.CharField(source="phase.color_code")
    index = serializers.IntegerField()
    error_min_distance_previous = serializers.CharField()
    warning_min_distance_next = serializers.CharField()

    def get_editable(self, deadline):
        request = self.context.get('request', None)
        try:
            if request.user.has_privilege(deadline.edit_privilege):
                return True
            else:
                return False

        except AttributeError:
            return False
