# Generated by Django 3.2.19 on 2024-06-27 08:05

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('projects', '0173_remove_deadline_deadlinesubgroup'),
    ]

    operations = [
        migrations.AlterField(
            model_name='attribute',
            name='help_link',
            field=models.URLField(blank=True, max_length=512, null=True, verbose_name='Help link'),
        ),
    ]
