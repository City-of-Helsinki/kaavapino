# Generated by Django 2.2.13 on 2020-06-17 10:46

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('projects', '0054_auto_20200611_0723'),
    ]

    operations = [
        migrations.AlterField(
            model_name='projectphase',
            name='project_subtype',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='phases', to='projects.ProjectSubtype', verbose_name='project subtype'),
        ),
    ]
