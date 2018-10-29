from rest_framework import viewsets

from projects.models import Project, ProjectPhase, ProjectType
from projects.serializers.project import (
    ProjectSerializer,
    ProjectPhaseSerializer,
    ProjectTypeSerializer,
)
from projects.serializers.projectschema import ProjectTypeSchemaSerializer


class ProjectTypeViewSet(viewsets.ModelViewSet):
    queryset = ProjectType.objects.all()
    serializer_class = ProjectTypeSerializer


class ProjectViewSet(viewsets.ModelViewSet):
    queryset = Project.objects.all()
    serializer_class = ProjectSerializer


class ProjectPhaseViewSet(viewsets.ModelViewSet):
    queryset = ProjectPhase.objects.all()
    serializer_class = ProjectPhaseSerializer


class ProjectTypeSchemaViewSet(viewsets.ModelViewSet):
    queryset = ProjectType.objects.all()
    serializer_class = ProjectTypeSchemaSerializer
