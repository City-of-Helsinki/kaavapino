# Generated by Django 2.2.13 on 2021-04-27 07:08

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('projects', '0107_auto_20210426_0932'),
    ]

    operations = [
        migrations.AddField(
            model_name='deadline',
            name='error_date_type_mismatch',
            field=models.TextField(blank=True, null=True, verbose_name='error message for date type mismatch'),
        ),
    ]
