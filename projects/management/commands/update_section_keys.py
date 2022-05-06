from django.core.cache import cache
from django.core.management.base import BaseCommand
from projects.models import ProjectCardSection


class Command(BaseCommand):
    help = "Update project card section keys"

    def handle(self, *args, **options):
        section_keys = {
            "Projektikortin kuva": "projektikortin_kuva",
            "Perustiedot": "perustiedot",
            "Suunnittelualueen kuvaus": "suunnittelualueen_kuvaus",
            "Strategiakytkentä": "strategiakytkenta",
            "Maanomistus ja sopimusmenettelyt": "maanomistus",
            "Kerrosalatiedot": "kerrosalatiedot",
            "Aikataulu": "aikataulu",
            "Yhteyshenkilöt": "yhteyshenkilöt",
            "Dokumentit": "dokumentit",
            "Suunnittelualueen rajaus": "suunnittelualueen_rajaus",
        }
        for section in ProjectCardSection.objects.filter(name__in=section_keys.keys()):
            print(f"Updating '{section.id}. {section.name}'")
            section.key = section_keys.get(section.name)
            section.save()
        
        print(f"Clearing cache...")
        cache.clear()
        print('All done!')
