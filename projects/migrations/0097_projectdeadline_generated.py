# Generated by Django 2.2.13 on 2021-01-21 05:44

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('projects', '0096_attribute_hide_conditions'),
    ]

    operations = [
        migrations.AddField(
            model_name='projectdeadline',
            name='generated',
            field=models.BooleanField(default=False, verbose_name='generated'),
        ),
    ]
