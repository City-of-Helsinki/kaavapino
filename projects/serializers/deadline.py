from rest_framework import serializers

from projects.models import Deadline


class DeadlineSerializer(serializers.Serializer):
    abbreviation = serializers.CharField()
    identifier = serializers.CharField()
    editable = serializers.SerializerMethodField()
    deadline_type = serializers.CharField()
    date_type_id = serializers.IntegerField(source="date_type.pk")
    error_past_due = serializers.CharField()
    phase_id = serializers.IntegerField(source="phase.pk")
    phase_name = serializers.IntegerField(source="phase.name")
    phase_color = serializers.IntegerField(source="phase.color")
    phase_color_code = serializers.IntegerField(source="phase.color_code")
    index = serializers.IntegerField()
    min_distance = serializers.IntegerField()
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
