# Generated by Django 3.2.19 on 2024-03-05 11:02

from django.db import migrations, models
from projects.models import Project
from django.utils import timezone


class Migration(migrations.Migration):

    dependencies = [
        ('projects', '0165_attribute_error_text'),
    ]

    def update_archived_at(self, schema_editor):
        for project in Project.objects.filter(archived=True, archived_at=None):
            project.archived_at = timezone.now()
            project.save()

    operations = [
        migrations.AddField(
            model_name='project',
            name='archived_at',
            field=models.DateTimeField(blank=True, null=True, verbose_name='archived at'),
        ),
        migrations.RunPython(update_archived_at, migrations.RunPython.noop),
    ]
