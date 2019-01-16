from rest_framework import serializers

from projects.filters import ProjectFilter
from projects.models import Report

FILTER_TYPE_DEFINITIONS = {
    "BooleanFilter": "boolean",
    "CharFilter": "string",
    "CharInFilter": "string",
    "DateTimeFilter": "datetime",
    "DateFilter": "date",
    "NumberFilter": "integer",
    "NumberInFilter": "integer",
    "UUIDFilter": "uuid",
    "UUIDInFilter": "uuid",
}


class ReportSerializer(serializers.ModelSerializer):
    filters = serializers.SerializerMethodField()

    class Meta:
        model = Report
        fields = ["id", "project_type", "name", "filters"]

    def get_filters(self, obj):
        filters = []
        project_filters = ProjectFilter.get_filters()

        for key, value in project_filters.items():
            filters.append(
                {
                    "identifier": key,
                    "type": FILTER_TYPE_DEFINITIONS[value.__class__.__name__],
                    "lookup": value.lookup_expr,
                }
            )

        return filters
