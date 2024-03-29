# Generated by Django 2.2.13 on 2021-12-09 23:18

import django.contrib.postgres.indexes
import django.contrib.postgres.search
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('projects', '0138_documenttemplate_silent_downloads'),
    ]

    operations = [
        migrations.AddField(
            model_name='project',
            name='vector_column',
            field=django.contrib.postgres.search.SearchVectorField(null=True),
        ),
        migrations.AddIndex(
            model_name='project',
            index=django.contrib.postgres.indexes.GinIndex(fields=['vector_column'], name='projects_pr_vector__6be585_gin'),
        ),
    ]
