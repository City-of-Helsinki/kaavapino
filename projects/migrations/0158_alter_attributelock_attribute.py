# Generated by Django 3.2.19 on 2023-09-27 12:11

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('projects', '0157_projectdocumentdownloadlog_invalidated'),
    ]

    operations = [
        migrations.AlterField(
            model_name='attributelock',
            name='attribute',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='attribute_lock', to='projects.attribute', verbose_name='attribute'),
        ),
    ]
