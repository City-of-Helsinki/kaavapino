from django.contrib.auth.models import Group
from helusers.models import AbstractUser

from users.groups import GROUPS


class User(AbstractUser):
    def is_in_group(self, group):
        if isinstance(group, Group):
            return self.groups.filter(group=group).exists()
        return self.groups.filter(name=group).exists()

    def is_in_any_of_groups(self, groups):
        if not groups:
            return False

        if isinstance(groups[0], Group):
            return self.groups.filter(group__in=groups).exists()
        return self.groups.filter(name__in=groups).exists()

    def is_administrative_personnel(self):
        admin_groups = list(GROUPS.ADMINISTRATIVE_PERSONNEL.values.keys())
        return self.is_in_any_of_groups(admin_groups)
