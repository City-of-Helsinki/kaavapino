import logging

from django.core.management.base import BaseCommand, CommandError

from projects.models import Attribute
from sitecontent.models import ListViewAttributeColumn

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Create default attribute column configuration for project list view"

    def handle(self, *args, **options):
        identifiers = ["hankenumero"]
        index = 1

        for identifier in identifiers:
            try:
                attr = Attribute.objects.get(identifier=identifier)
            except Attribute.DoesNotExist:
                logger.warning(f"{identifier} not found, skipping")

            ListViewAttributeColumn.objects.update_or_create(
                attribute=attr,
                defaults={"index": index},
            )
            index += 1
