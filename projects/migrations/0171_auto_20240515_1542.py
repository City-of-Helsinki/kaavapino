# Generated by Django 3.2.19 on 2024-05-15 12:42

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('projects', '0170_auto_20240515_1418'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='deadline',
            name='deadlinegroup',
        ),
        migrations.RemoveField(
            model_name='deadline',
            name='deadlinesubgroup',
        ),
        migrations.AddField(
            model_name='attribute',
            name='attributegroup',
            field=models.TextField(blank=True, null=True, verbose_name='attribute group'),
        ),
        migrations.AddField(
            model_name='attribute',
            name='attributesubgroup',
            field=models.TextField(blank=True, null=True, verbose_name='attribute subgroup'),
        ),
    ]