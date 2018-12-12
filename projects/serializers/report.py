from rest_framework import serializers

from projects.models import Report


class ReportSerializer(serializers.ModelSerializer):
    filters = serializers.SerializerMethodField()

    class Meta:
        model = Report
        fields = ["id", "project_type", "name", "filters"]

    def get_filters(self, obj):
        return []
