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
        project_deadlines = ProjectDeadline.objects.filter(project=project)
        to_be_removed = []
        dont_delete = [] # Identifiers that should not be deleted from attribute_data, but possibly from ProjectDeadlines
        for project_dl in project_deadlines:
            if project_dl.deadline.subtype != project.subtype:
                to_be_removed.append(project_dl)
                continue
            if not project.create_draft and project_dl.deadline.phase.name == "Luonnos":
                to_be_removed.append(project_dl)
                continue
            if not project.create_principles and project_dl.deadline.phase.name == "Periaatteet":
                to_be_removed.append(project_dl)
                continue
            dont_delete.append(project_dl)
        dont_delete = [p_dl.deadline.attribute.identifier for p_dl in dont_delete if p_dl.deadline.attribute]

        try:
            with transaction.atomic():
                for dl in to_be_removed:
                    logger.info("Deleting " + str(dl.deadline))
                    if dl.deadline.attribute:
                        attr_value = project.attribute_data.get(dl.deadline.attribute.identifier)
                        if attr_value and not dl.deadline.attribute.identifier in dont_delete:
                            # Fix attribute_data
                            correct_value = project.deadlines.filter(deadline__attribute__identifier=dl.deadline.attribute.identifier,
                                                                     deadline__subtype=project.subtype).first()
                            if correct_value:
                                print("Found correct value for " + str(dl.deadline)," Setting to " + str(correct_value))
                                project.attribute_data[dl.deadline.attribute.identifier] = correct_value
                            else:
                                print("Removing incorrect value from attribute_data " + str(dl.deadline))
                                project.attribute_data.pop(dl.deadline.attribute.identifier)
                    # Remove incorrect ProjectDeadline(s)
                    dl.delete()
                confirmation = input("OK to clear the above deadlines? (y/n)")
                if confirmation != 'y':
                    raise Exception
                project.save()
                logger.info("Bad deadlines cleared.")
                clear_cache()
        except Exception as e:
            logger.info(e)
            logger.info("Removal canceled.")

    