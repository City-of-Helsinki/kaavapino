import logging

from django.core.management.base import BaseCommand

from projects.models import Project

logger = logging.getLogger(__name__)

# Creates indexes by re-saving all projects
class Command(BaseCommand):
    help = "Index all projects"

    def handle(self, *args, **options):
        for project in Project.objects.all():
            project.save()
