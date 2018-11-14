from django.db import transaction
from private_storage.views import PrivateStorageDetailView
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.parsers import MultiPartParser
from rest_framework.response import Response

from projects.models import Project, ProjectPhase, ProjectType, ProjectAttributeFile
from projects.serializers.project import (
    ProjectSerializer,
    ProjectPhaseSerializer,
    ProjectFileSerializer,
)
from projects.serializers.projectschema import ProjectTypeSchemaSerializer
from projects.serializers.projecttype import ProjectTypeSerializer


class ProjectTypeViewSet(viewsets.ModelViewSet):
    queryset = ProjectType.objects.all()
    serializer_class = ProjectTypeSerializer


class ProjectViewSet(viewsets.ModelViewSet):
    queryset = Project.objects.all()
    serializer_class = ProjectSerializer

    @action(methods=["put"], detail=True, parser_classes=[MultiPartParser])
    def files(self, request, pk=None):
        project = self.get_object()
        request.data["project"] = project.pk

        serializer = ProjectFileSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        with transaction.atomic():
            # Remove any file using the same attribute for the project
            ProjectAttributeFile.objects.filter(
                attribute=serializer.validated_data["attribute"], project=project
            ).delete()

            # Save the new file and metadata to disk
            serializer.save()

        return Response(serializer.data)


class ProjectPhaseViewSet(viewsets.ModelViewSet):
    queryset = ProjectPhase.objects.all()
    serializer_class = ProjectPhaseSerializer


class ProjectTypeSchemaViewSet(viewsets.ModelViewSet):
    queryset = ProjectType.objects.all()
    serializer_class = ProjectTypeSchemaSerializer
