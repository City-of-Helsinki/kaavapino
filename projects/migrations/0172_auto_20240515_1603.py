# Generated by Django 3.2.19 on 2024-05-15 13:03

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('projects', '0171_auto_20240515_1542'),
    ]

    operations = [
        migrations.AlterField(
            model_name='attribute',
            name='attributegroup',
            field=models.TextField(blank=True, null=True, verbose_name='attributegroup'),
        ),
        migrations.AlterField(
            model_name='attribute',
            name='attributesubgroup',
            field=models.TextField(blank=True, null=True, verbose_name='attributesubgroup'),
        ),
    ]