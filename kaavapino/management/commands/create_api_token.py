from django.core.management.base import BaseCommand, CommandError
from rest_framework.authtoken.models import Token

from users.models import User


class Command(BaseCommand):
    help = 'Create or fetch API token for given user for development purposes'

    def add_arguments(self, parser):
        parser.add_argument('username', type=str, help='Username')

    def handle(self, **options):
        try:
            user = User.objects.get(username=options['username'])
        except User.DoesNotExist:
            raise CommandError('Username not found')

        try:
            token = Token.objects.get(user=user)
        except Token.DoesNotExist:
            token = Token.objects.create(user=user)

        print(token.key)
