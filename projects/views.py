from rest_framework import viewsets

from projects.models import Project, ProjectPhase, ProjectType
from projects.serializers.project import ProjectSerializer, ProjectPhaseSerializer
from projects.serializers.projectschema import ProjectTypeSchemaSerializer
from projects.serializers.projecttype import ProjectTypeSerializer


class ProjectTypeViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = ProjectType.objects.all()
    serializer_class = ProjectTypeSerializer


class ProjectViewSet(viewsets.ModelViewSet):
    queryset = Project.objects.all()
    serializer_class = ProjectSerializer


class ProjectPhaseViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = ProjectPhase.objects.all()
    serializer_class = ProjectPhaseSerializer


class ProjectTypeSchemaViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = ProjectType.objects.all()
    serializer_class = ProjectTypeSchemaSerializer
