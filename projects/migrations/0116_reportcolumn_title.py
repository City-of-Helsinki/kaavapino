# Generated by Django 2.2.13 on 2021-08-06 05:01

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('projects', '0115_report_column'),
    ]

    operations = [
        migrations.AddField(
            model_name='reportcolumn',
            name='title',
            field=models.CharField(blank=True, max_length=255, null=True, verbose_name='title'),
        ),
    ]
