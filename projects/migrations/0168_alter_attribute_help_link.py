# Generated by Django 3.2.19 on 2024-07-08 08:06

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('projects', '0167_attribute_fieldset_total'),
    ]

    operations = [
        migrations.AlterField(
            model_name='attribute',
            name='help_link',
            field=models.URLField(blank=True, max_length=512, null=True, verbose_name='Help link'),
        ),
    ]
