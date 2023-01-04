from rest_framework import serializers
from typing import Any, Optional

from projects.models import Report, ReportFilter, Attribute

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


class ReportFilterSerializer(serializers.ModelSerializer):
    choices = serializers.SerializerMethodField()

    def get_choices(self, report_filter: ReportFilter) -> Optional[list[dict[str, Any]]]:
        if not report_filter.attributes_as_choices:
            choices: list[dict[str, Any]] = []
            attr: Attribute
            for attr in report_filter.attributes.all():
                choices += [
                    {
                        "value": choice.value,
                        "identifier": choice.identifier,
                    }
                    for choice in attr.value_choices.all()
                ]
        elif not report_filter.attribute_choices.count():
            choices = [
                {
                    "value": attr.name,
                    "identifier": attr.identifier,
                }
                for attr in report_filter.attributes.all()
            ]
        else:
            choices = [
                {
                    "value": choice.name,
                    "identifier": choice.identifier,
                }
                for choice in report_filter.attribute_choices.all()
            ]

        return choices or None

    class Meta:
        model = ReportFilter
        fields = [
            "name",
            "identifier",
            "type",
            "input_type",
            "choices",
        ]


class ReportSerializer(serializers.ModelSerializer):
    filters = serializers.SerializerMethodField()
    preview_title_column = serializers.SerializerMethodField()

    def get_filters(self, report: Report) -> list[dict[str, Any]]:
        return [
            ReportFilterSerializer(report_filter).data
            for report_filter in report.filters.all()
        ]

    def get_preview_title_column(self, report: Report) -> Optional[str]:
        try:
            return report.columns.filter(
                preview_title_column=True
            ).first().title
        except AttributeError:
            return None

    class Meta:
        model = Report
        fields = [
            "id",
            "project_type",
            "name",
            "previewable",
            "filters",
            "preview_title_column",
        ]
