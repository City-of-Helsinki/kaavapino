from django.urls import reverse
from rest_framework import serializers

from projects.models import DocumentTemplate


class DocumentTemplateSerializer(serializers.ModelSerializer):
    file = serializers.SerializerMethodField()
    phase = serializers.PrimaryKeyRelatedField(source="project_phase", read_only=True)
    phase_name = serializers.SlugField(source="project_phase.name", read_only=True)
    phase_index = serializers.SerializerMethodField()

    class Meta:
        model = DocumentTemplate
        fields = ["id", "name", "file", "phase", "phase_name", "phase_index"]
        read_only_fields = ["id", "name"]

    def get_file(self, document_template):
        request = self.context["request"]
        project_id = self.context["project"].id
        url = reverse(
            "documenttemplate-detail",
            kwargs={"project_pk": project_id, "slug": document_template.slug},
        )
        absolute_url = request.build_absolute_uri(url)
        return absolute_url

    def get_phase_index(self, document_template):
        return document_template.project_phase.index
