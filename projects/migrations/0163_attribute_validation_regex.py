# Generated by Django 3.2.19 on 2023-10-25 09:57

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('projects', '0162_attribute_assistive_text'),
    ]

    operations = [
        migrations.AddField(
            model_name='attribute',
            name='validation_regex',
            field=models.CharField(blank=True, max_length=64, null=True, verbose_name='validation regex'),
        ),
    ]