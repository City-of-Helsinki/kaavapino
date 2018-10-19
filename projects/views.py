from rest_framework import viewsets

from projects.models import Project
from projects.serializers.project import ProjectSerializer


class ProjectViewSet(viewsets.ModelViewSet):
    queryset = Project.objects.all()
    serializer_class = ProjectSerializer
