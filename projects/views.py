from rest_framework import viewsets

from projects.models import Project, ProjectPhase
from projects.serializers.project import ProjectSerializer, ProjectPhaseSerializer


class ProjectViewSet(viewsets.ModelViewSet):
    queryset = Project.objects.all()
    serializer_class = ProjectSerializer


class ProjectPhaseViewSet(viewsets.ModelViewSet):
    queryset = ProjectPhase.objects.all()
    serializer_class = ProjectPhaseSerializer
