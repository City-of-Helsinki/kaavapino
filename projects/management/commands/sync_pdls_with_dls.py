import logging
from django.core.management.base import BaseCommand
from django.db import transaction
from django.core.cache import cache

from projects.models import Project,ProjectDeadline
from sitecontent.admin import clear_cache

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Sets projects.deadlines to all ProjectDeadlines related to a given project. Used when they have gone out of sync."

    def add_arguments(self, parser):
        parser.add_argument("--id", nargs="?", type=int)

    def handle(self, *args, **options):
        project_id = options.get("id")
        if not project_id:
            logger.warning("No project id specified, exiting.")
            return

        project = Project.objects.get(pk=project_id)
        project_deadlines = ProjectDeadline.objects.filter(project=project)
        try:
            with transaction.atomic():
                current_dls = project.deadlines.filter()
                for p_dl in project_deadlines:
                    if p_dl not in current_dls:
                        logger.info("Synchronizing missing deadline", str(p_dl))
                        if p_dl.deadline.attribute:
                            attr_value = project.attribute_data.get(p_dl.deadline.attribute.identifier)
                            if attr_value:
                                p_dl.date = attr_value
                                logger.info("Copied value from attribute_data:" + str(attr_value))
                                p_dl.save()
                confirmation = input("OK to apply above changes? (y/n)")
                if confirmation != 'y':
                    raise Exception
                project.deadlines.set(project_deadlines)
                project.save()
                logger.info("Deadlines synchronized.")
                clear_cache()
        except Exception as e:
            logger.info(e)
            logger.info("Sync canceled.")

    