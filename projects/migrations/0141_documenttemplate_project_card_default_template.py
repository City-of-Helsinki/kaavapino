# Generated by Django 3.2.10 on 2022-01-27 11:58

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('projects', '0140_auto_20211220_1649'),
    ]

    operations = [
        migrations.AddField(
            model_name='documenttemplate',
            name='project_card_default_template',
            field=models.BooleanField(default=False, verbose_name='project card default template'),
        ),
    ]
