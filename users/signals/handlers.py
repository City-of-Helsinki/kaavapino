from django.contrib.auth.models import Group
from django.db.models.signals import post_save
from django.dispatch import receiver

from users.models import User, GroupPrivilege


@receiver(post_save, sender=User)
def add_admin_group_post_user_creation(sender, instance, created, *args, **kwargs):
    if created and instance.is_staff:
        admin_group = Group.objects.filter(groupprivilege__privilege_level='admin').first()
        if admin_group:
            instance.groups.add(admin_group)
    elif not instance.is_staff and instance.has_privilege('admin'):
        instance.is_staff = True
        instance.save()
    elif instance.is_staff and not instance.has_privilege('admin'):
        instance.is_staff = False
        instance.save()
