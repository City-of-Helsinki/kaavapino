from django.contrib.auth.models import Group
from django.db.models.signals import post_save, m2m_changed
from django.dispatch import receiver

from users.models import User, GroupPrivilege


@receiver(post_save, sender=User)
def add_admin_group_post_user_creation(sender, instance, created, *args, **kwargs):
    if created and (instance.is_staff or instance.is_superuser):
        admin_group = Group.objects.filter(groupprivilege__privilege_level='admin').first()
        if not admin_group:
            admin_group = Group.objects.get_or_create(name='Administrators')[0]
            GroupPrivilege.objects.update_or_create(
                group=admin_group,
                privilege_level='admin',
            )

        instance.groups.add(admin_group)
    elif not instance.is_staff and instance.has_privilege('admin'):
        instance.is_staff = True
        instance.is_superuser = True
        instance.save()
    elif instance.is_staff and not instance.has_privilege('admin'):
        instance.is_staff = False
        instance.is_superuser = True
        instance.save()

@receiver(m2m_changed, sender=User.additional_groups.through)
def handle_additional_groups(sender, instance, action, pk_set, **kwargs):
    if action == "post_add":
        group_pks = set([group.pk for group in instance.groups.all()])
        for pk in pk_set:
            if pk not in group_pks:
                combined_groups = instance.groups.all() | instance.additional_groups.all()
                instance.groups.set(combined_groups)
                instance.save()
                break

    if action == "post_remove":
        instance.groups.set(instance.groups.exclude(pk__in=pk_set))
        instance.save()
