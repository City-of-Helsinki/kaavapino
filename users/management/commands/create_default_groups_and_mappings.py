from django.core.management.base import BaseCommand, CommandError

from helusers.models import ADGroup, ADGroupMapping
from users.models import Group, GroupPrivilege

GROUPS = [
    ("sg_kymp_kayttajat", "browse", "Selaajat"),
    ("sg_kymp_org_maka", "edit", "Asiantuntijat"),
    ("sg_kymp_org_maka_aska", "create", "Vastuuhenkilöt"),
    (None, "admin", "Pääkäyttäjät"),
]

class Command(BaseCommand):
    help = "Create default groups with privileges and AD mappings"

    def handle(self, *args, **options):
        for (ad_group_name, privilege_level, group_name) in GROUPS:
            group, _ = Group.objects.get_or_create(name=group_name)
            GroupPrivilege.objects.create(group=group, privilege_level=privilege_level)

            if ad_group_name:
                ad_group, created = ADGroup.objects.get_or_create(name=ad_group_name.lower())

                if created:
                    ad_group.display_name = ad_group_name
                    ad_group.save()

                ADGroupMapping.objects.create(group=group, ad_group=ad_group)
