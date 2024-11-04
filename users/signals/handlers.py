import requests

from django.conf import settings
from django.contrib.auth.models import Group
from django.db.models.signals import post_save, pre_save, m2m_changed
from django.dispatch import receiver

from users.models import User, GroupPrivilege
from users.helpers import get_graph_api_access_token

from projects.models import Project

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


@receiver(post_save, sender=User)
def update_user_ad_data(sender, instance, *args, **kwargs):
    if instance.ad_id and instance.department_name:
        return

    token = get_graph_api_access_token()
    if not token or not instance.email:
        return

    response = requests.get(
        f"{settings.GRAPH_API_BASE_URL}/v1.0/users/?$search=\"mail:{instance.email}\"",
        headers={
            "Authorization": f"Bearer {token}",
            "consistencyLevel": "eventual",
        },
    )

    if not response:
        return

    changed = False

    if not instance.ad_id:
        try:
            ad_id = response.json().get("value")[0]["id"]
            if ad_id:
                instance.ad_id = ad_id
                changed = True
        except (TypeError, IndexError, KeyError):
            pass

    if not instance.department_name:
        try:
            department_name = response.json().get("value")[0]["officeLocation"]
            if department_name:
                instance.department_name = department_name
                changed = True
        except (TypeError, IndexError, KeyError):
            pass

    if changed:
        instance.save()

@receiver(pre_save, sender=User)
def update_existing_user(sender, instance, raw, using, update_fields, *args, **kwargs):
    # For migrating users during tunnistamo-helsinkiprofiili (keycloak) transition
    old_users = []
    try:
        if not instance.username.startswith('u-'):
            old_users = User.objects.filter(username=instance.username)
    except AttributeError:
        pass
    if not old_users and instance.email:
        old_users = User.objects.filter(email__iexact=instance.email, username__startswith="u-")
    if not old_users:
        return
    old_user = next((user for user in old_users if user.id == instance.id), old_users[0])
    instance.id = old_user.id


@receiver(post_save, sender=User)
def update_responsible_uuid(sender, instance, *args, **kwargs):
    projects = Project.objects.filter(user_id=instance.id)
    for project in projects:
        if instance.uuid and (str(instance.uuid) != project.attribute_data['vastuuhenkilo_nimi']):
            project.attribute_data['vastuuhenkilo_nimi'] = instance.uuid
            if 'vastuuhenkilo_nimi_readonly' in project.attribute_data:
                project.attribute_data['vastuuhenkilo_nimi_readonly']=instance.uuid
            project.save()

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
