# Generated by Django 3.2.16 on 2023-04-21 09:14

import requests

from django.db import migrations
from django.conf import settings
import logging

from users.helpers import get_graph_api_access_token


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0010_alter_user_managers'),
    ]

    def set_department_names(apps, schema_editor):
        token = get_graph_api_access_token()
        if not token:
            return

        User = apps.get_model('users', 'User')
        for user in User.objects.all():
            if user.department_name or not user.email:
                continue

            response = requests.get(
                f"{settings.GRAPH_API_BASE_URL}/v1.0/users/?$search=\"mail:{user.email}\"",
                headers={
                    "Authorization": f"Bearer {token}",
                    "consistencyLevel": "eventual",
                },
            )

            if response:
                try:
                    user.department_name = response.json().get("value")[0]["officeLocation"]
                    user.save()
                except (TypeError, IndexError, KeyError):
                    pass

    operations = [
        migrations.RunPython(set_department_names, migrations.RunPython.noop)
    ]
