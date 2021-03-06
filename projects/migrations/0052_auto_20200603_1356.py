# Generated by Django 2.1.4 on 2020-06-03 10:56

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('projects', '0051_attribute_help_link'),
    ]

    def set_default_user(apps, schema_editor):
        Project = apps.get_model('projects', 'Project')
        User = apps.get_model('users', 'User')

        if len(Project.objects.filter(user__isnull=False)):
            try:
                user = User.objects.filter(username="asd")[0]
            except IndexError:
                raise User.DoesNotExist('At least one admin user is needed to migrate existing projects')

            for project in Project.objects.filter(user__isnull=False):
                project.user = user


    operations = [
        migrations.RunPython(set_default_user),
        migrations.AlterField(
            model_name='project',
            name='user',
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='projects', to=settings.AUTH_USER_MODEL, verbose_name='user'),
        ),
    ]
