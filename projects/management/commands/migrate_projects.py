import logging
import numpy
import copy

from django.core.management.base import BaseCommand
from projects.models import Project, ProjectDeadline
from django.db import transaction

from projects.serializers.utils import get_dl_vis_bool_name
from users.models import User

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Update projects to work with V1.1"

    def add_arguments(self, parser):
        parser.add_argument("--id", nargs="?", type=int)
        parser.add_argument("--userid", nargs="?", type=int)
        parser.add_argument("--commit", action='store_true')
        parser.add_argument("--verbose", action='store_true')

    def handle(self, *args, **options):
        project_id = options.get("id")
        user_id = options.get("userid")
        commit = options.get("commit")
        verbose = options.get("verbose")

        if project_id:
            try:
                projects = [Project.objects.get(pk=project_id)]
            except Project.DoesNotExist:
                projects = Project.objects.all()
        else:
            projects = Project.objects.all()

        user = User.objects.get(id=user_id)

        confirmation = input(f"Migrate {len(projects)} projects as user {user.username}? (y/n)\n")
        if confirmation != 'y':
            return

        with transaction.atomic():
            for idx, project in enumerate(projects,start=1):
                logging.info(f'> Migrating project {project.name} ({idx}/{len(projects)})')
                applicable_deadlines = project.get_applicable_deadlines(initial=True)
                current_project_deadlines = project.deadlines.all()
                current_deadlines = [dl.deadline for dl in current_project_deadlines]

                to_be_added = [dl for dl in applicable_deadlines if dl not in current_deadlines]
                to_be_preserved = [dl for dl in current_deadlines if dl in applicable_deadlines]
                to_be_removed = [dl for dl in current_deadlines if dl not in applicable_deadlines]

                original_attribute_data = copy.deepcopy(project.attribute_data)

                # Add newly created deadlines
                project_deadlines = list(ProjectDeadline.objects.filter(project=project, deadline__in=applicable_deadlines))
                generated_deadlines = []
                for deadline in to_be_added:
                    new_project_deadline = ProjectDeadline.objects.create(
                        project=project,
                        deadline=deadline,
                        generated=True
                    )
                    if verbose: logging.info(f'Created ProjectDeadline {new_project_deadline.deadline.attribute.identifier}')
                    if deadline.deadlinegroup:
                        vis_bool = get_dl_vis_bool_name(deadline.deadlinegroup)
                        if vis_bool and not vis_bool in project.attribute_data:
                            project.attribute_data[vis_bool] = True if deadline.deadlinegroup.endswith('1') else False
                            if verbose: logging.info(f'Set vis_bool {vis_bool}={project.attribute_data[vis_bool]}')
                    generated_deadlines.append(new_project_deadline)
                    project_deadlines.append(new_project_deadline)
                project.deadlines.set(project_deadlines)

                # Delete deadlines that are no longer needed
                for deadline in to_be_removed:
                    previous_value = project.attribute_data.pop(deadline.attribute.identifier, None)
                    if verbose and previous_value: logging.info(f"Removed attribute {deadline.attribute.identifier} from attribute_data")
                ProjectDeadline.objects.filter(project=project, deadline__in=to_be_removed).delete()

                project.save()

                # Calculate date values for new deadlines, project attribute_data is updated within method
                results = project._set_calculated_deadlines(
                    deadlines=to_be_added,
                    user=user,
                    initial=True,
                )
                if verbose: logging.info(f'Set calculated deadlines: {results}')

                updated_attribute_data = project.attribute_data
                changed_attribute_data = numpy.setdiff1d(list(updated_attribute_data.keys()), list(original_attribute_data.keys()))
                if verbose: logging.info(f'Changed attribute_data: {", ".join(changed_attribute_data)}')

                logging.info(f'> Project {project.name} updated. (Added: {len(to_be_added)}, Removed: {len(to_be_removed)}, Preserved: {len(to_be_preserved)})\n')

            # Set rollback=True if no commit flag is given in manage.py command
            transaction.set_rollback(rollback=True if not commit else False)