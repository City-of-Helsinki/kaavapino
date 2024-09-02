from django.core.management.base import BaseCommand

from projects.models import Project
from users.models import User


class Command(BaseCommand):
    help = "For updating outdated uuid for responsible person after migrating to keycloak. Needs to be run once only."

    def add_arguments(self, parser):
        parser.add_argument("--commit", action='store_true')

    def handle(self, *args, **options):
        affected_count = 0
        if not options['commit']:
            print("Dry run, use --commit to make changes to database")
        for project in Project.objects.all():
            user = User.objects.get(id=project.user_id)
            if str(user.uuid) != project.attribute_data['vastuuhenkilo_nimi']:
                if options['commit']:
                    project.attribute_data['vastuuhenkilo_nimi']=user.uuid
                    if 'vastuuhenkilo_nimi_readonly' in project.attribute_data:
                        project.attribute_data['vastuuhenkilo_nimi_readonly']=user.uuid
                    project.save()
                print("Affected project " + str(project.id))
                affected_count += 1
        print(str(affected_count) + " projects affected")
