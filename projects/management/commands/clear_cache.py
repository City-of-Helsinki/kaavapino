from django.core.management.base import BaseCommand
from django.core.cache import cache

import logging

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = "Helper command for clearing cache"

    def __init__(self):
        super().__init__()

    def handle(self, *args, **options):
        try:
            print(f'Clearing cache...')
            cache.clear()
            print(f'Cache cleared!')
        except Exception as exc:
            logger.warning("Error while clearing cache", exc)