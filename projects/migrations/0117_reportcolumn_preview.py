# Generated by Django 2.2.13 on 2021-08-09 06:18

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('projects', '0116_reportcolumn_title'),
    ]

    operations = [
        migrations.AddField(
            model_name='reportcolumn',
            name='preview',
            field=models.BooleanField(default=True, verbose_name='include in preview'),
        ),
    ]
