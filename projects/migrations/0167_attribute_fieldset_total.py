# Generated by Django 3.2.19 on 2024-03-13 13:57

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('projects', '0166_project_archived_at'),
    ]

    operations = [
        migrations.AddField(
            model_name='attribute',
            name='fieldset_total',
            field=models.TextField(blank=True, null=True, verbose_name='fieldset total'),
        ),
    ]
