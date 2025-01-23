import logging
from django.core.management.base import BaseCommand
from django.db import transaction
from django.core.cache import cache

from projects.models import Project,ProjectDeadline
from sitecontent.admin import clear_cache

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Removes deadlines from project data if they are not supposed to be visible. Don't use after 1.1."

    def add_arguments(self, parser):
        parser.add_argument("--id", nargs="?", type=int)

    def handle(self, *args, **options):
        project_id = options.get("id")
        if not project_id:
            logger.warning("No project id specified, exiting.")
            return
        
        project = Project.objects.get(pk=project_id)
        deadline_test = ProjectDeadline.objects.filter(project=project)
        try:
            with transaction.atomic():
                # Remove irrelevant deadlines from project data
                project.update_deadlines()
                # Remove projectDeadline associated with this project from the bad ones
                for dl in deadline_test:
                    if dl.deadline.subtype != project.subtype:
                        dl.delete()
                        logger.info("Deleting " + str(dl.deadline))
                        continue
                confirmation = input("OK to clear the above deadlines? (y/n)")
                if confirmation != 'y':
                    raise Exception
                project.save()
                logger.info("Bad deadlines cleared.")
                clear_cache()
        except:
            logger.info("Removal canceled.")

    