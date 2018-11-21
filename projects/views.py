from django.db import transaction
from private_storage.views import PrivateStorageDetailView
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.parsers import MultiPartParser
from rest_framework.response import Response

from projects.models import Project, ProjectPhase, ProjectType, ProjectAttributeFile
from projects.models.project import ProjectSubtype
from projects.permissions.media_file_permissions import (
    has_project_attribute_file_permissions,
)
from projects.serializers.project import (
    ProjectSerializer,
    ProjectPhaseSerializer,
    ProjectFileSerializer,
)
from projects.serializers.projectschema import ProjectTypeSchemaSerializer
from projects.serializers.projecttype import (
    ProjectTypeSerializer,
    ProjectSubtypeSerializer,
)


class ProjectTypeViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = ProjectType.objects.all()
    serializer_class = ProjectTypeSerializer


class ProjectViewSet(viewsets.ModelViewSet):
    queryset = Project.objects.all()
    serializer_class = ProjectSerializer

    @action(methods=["put"], detail=True, parser_classes=[MultiPartParser])
    def files(self, request, pk=None):
        project = self.get_object()

        # Query dicts are not mutable by default, temporarily change that
        request.data._mutable = True
        request.data["project"] = project.pk
        request.data._mutable = False

        context = self.get_serializer_context()
        serializer = ProjectFileSerializer(data=request.data, context=context)
        serializer.is_valid(raise_exception=True)

        with transaction.atomic():
            # Remove any file using the same attribute for the project
            ProjectAttributeFile.objects.filter(
                attribute=serializer.validated_data["attribute"], project=project
            ).delete()

            # Save the new file and metadata to disk
            serializer.save()

        return Response(serializer.data)


class ProjectPhaseViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = ProjectPhase.objects.all()
    serializer_class = ProjectPhaseSerializer


class ProjectTypeSchemaViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = ProjectType.objects.all()
    serializer_class = ProjectTypeSchemaSerializer


class ProjectSubtypeViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = ProjectSubtype.objects.all()
    serializer_class = ProjectSubtypeSerializer


class ProjectAttributeFileDownloadView(PrivateStorageDetailView):
    model = ProjectAttributeFile
    slug_field = "file"
    slug_url_kwarg = "path"

    def get_queryset(self):
        # Queryset that is allowed to be downloaded
        return ProjectAttributeFile.objects.all()

    def can_access_file(self, private_file):
        # NOTE: This overrides PRIVATE_STORAGE_AUTH_FUNCTION
        # TODO: Change permission function when user permissions has been implemented
        return has_project_attribute_file_permissions(private_file, self.request)
