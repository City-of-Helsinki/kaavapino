# Generated by Django 3.2.25 on 2025-05-08 06:25

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('projects', '0181_attribute_api_visibility'),
    ]

    operations = [
        migrations.AddField(
            model_name='projectdeadline',
            name='editable',
            field=models.BooleanField(default=True, verbose_name='editable'),
        ),
    ]
