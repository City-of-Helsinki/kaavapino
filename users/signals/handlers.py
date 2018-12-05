from django.contrib.auth.models import Group
from django.db.models.signals import post_save
from django.dispatch import receiver

from users.groups import GROUPS
from users.models import User


@receiver(post_save, sender=User)
def add_admin_group_post_user_creation(sender, instance, created, *args, **kwargs):
    if created and instance.is_superuser:
        admin_group = Group.objects.filter(name=GROUPS.ADMINISTRATOR).first()
        if admin_group:
            instance.groups.add(admin_group)
