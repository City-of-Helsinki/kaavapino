from django.core.management.base import BaseCommand
from django.db import transaction

from projects.models import Project

import logging

log = logging.getLogger(__name__)

class Command(BaseCommand):
    help = "Update project deadlines"

    def add_arguments(self, parser):
        parser.add_argument("--id", nargs="?", type=int)

    def handle(self, *args, **options):
        project_id = options.get("id")

        if project_id:
            try:
                projects = [Project.objects.get(pk=project_id)]
            except Project.DoesNotExist:
                projects = Project.objects.all()
        else:
            projects = Project.objects.all()

        for idx, project in enumerate(projects):
            log.info(f'Updating project "{project.name}" deadlines ({idx+1}/{len(projects)})')
            with transaction.atomic():
                project.update_deadlines()
                project.save()