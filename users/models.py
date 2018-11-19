from django.contrib.auth.models import Group
from helusers.models import AbstractUser


class User(AbstractUser):
    def is_in_group(self, group):
        if isinstance(group, Group):
            return self.groups.filter(group=group).exists()
        return self.groups.filter(name=group).exists()
