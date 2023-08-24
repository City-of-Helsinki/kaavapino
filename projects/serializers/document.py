from django.urls import reverse
from drf_spectacular.utils import extend_schema_field, inline_serializer
from drf_spectacular.types import OpenApiTypes
from rest_framework import serializers

from projects.models import DocumentTemplate, ProjectPhase


class DocumentTemplateSerializer(serializers.ModelSerializer):
    file = serializers.SerializerMethodField()
    preview_file = serializers.SerializerMethodField()
    last_downloaded = serializers.SerializerMethodField()
    phases = serializers.SerializerMethodField()

    class Meta:
        model = DocumentTemplate
        fields = [
            "id",
            "name",
            "image_template",
            "file",
            "preview_file",
            "last_downloaded",
            "phases",
            "silent_downloads",
        ]
        read_only_fields = ["id", "name", "image_template"]

    @extend_schema_field(OpenApiTypes.STR)
    def get_file(self, document_template):
        request = self.context["request"]
        project_id = self.context["project"].id
        url = reverse(
            "documenttemplate-detail",
            kwargs={"project_pk": project_id, "slug": document_template.slug},
        )
        absolute_url = request.build_absolute_uri(url)
        return absolute_url

    @extend_schema_field(OpenApiTypes.STR)
    def get_preview_file(self, document_template):
        return self.get_file(document_template) + "?preview=true"

    @extend_schema_field(OpenApiTypes.DATE)
    def get_last_downloaded(self, document_template):
        try:
            last_downloaded = document_template.document_download_log \
                .filter(project=self.context["project"], invalidated=False) \
                .order_by("-created_at") \
                .first().created_at
        except AttributeError:
            last_downloaded = None

        return last_downloaded

    @extend_schema_field(inline_serializer(
        name='phases',
        fields={
            'phase_index': serializers.IntegerField(),
            'phase_name': serializers.CharField(),
            'phase_ended': serializers.BooleanField(),
            'last_downloaded': serializers.DateField(),
        },
        many=True,
    ))
    def get_phases(self, document_template):
        phases = document_template.common_project_phases.all()
        phase_list = []
        project = self.context["project"]

        for phase in phases:
            try:
                project_phase = phase.phases.get(
                    project_subtype=project.subtype,
                )
            except ProjectPhase.DoesNotExist:
                continue

            try:
                last_downloaded = document_template.document_download_log \
                    .filter(project=project) \
                    .filter(phase=phase) \
                    .filter(invalidated=False) \
                    .order_by("-created_at") \
                    .first().created_at
            except AttributeError:
                last_downloaded = None

            phase_ended = project_phase.index < project.phase.index
            phase_list.append({
                "phase_index": project_phase.index or project_phase.common_project_phase.index,
                "phase_name": phase.prefixed_name,
                "phase_ended": phase_ended,
                "last_downloaded": last_downloaded,
            })

        return phase_list
