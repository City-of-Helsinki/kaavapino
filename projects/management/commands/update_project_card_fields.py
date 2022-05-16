from django.core.management.base import BaseCommand
from projects.models import (
        Attribute,
        ProjectCardSection,
        ProjectCardSectionAttribute,
)


class Command(BaseCommand):
    help = "Update project card section keys"

    def handle(self, *args, **options):
        check = ProjectCardSectionAttribute.objects.filter(
            custom_label__in=("Alueella on kaupungin maanomistusta",
                              "Alueella on yksityistä maanomistusta"))
        if check.exists():
            print("This command has already been ran")
            return

        toteuttamissopimus_tarve = Attribute.objects.get(identifier="toteuttamissopimus_tarve")
        maankayttosopimus_tarve = Attribute.objects.get(identifier="maankayttosopimus_tarve")
        muu_kuin_kaupungin_maanomistus = Attribute.objects.get(identifier="muu_kuin_kaupungin_maanomistus")

        section = ProjectCardSection.objects.get(key="maanomistus")

        # Update section indexes
        for a in section.attributes.all():
            a.index = a.index + 3

        ProjectCardSectionAttribute.objects.create(
            attribute=toteuttamissopimus_tarve,
            section=section,
            custom_label="Alueella on kaupungin maanomistusta",
            index=0,
        )

        ProjectCardSectionAttribute.objects.create(
            attribute=maankayttosopimus_tarve,
            section=section,
            custom_label="Alueella on yksityistä maanomistusta",
            index=1,
        )

        ProjectCardSectionAttribute.objects.create(
            attribute=muu_kuin_kaupungin_maanomistus,
            section=section,
            index=2,
        )
