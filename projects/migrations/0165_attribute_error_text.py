# Generated by Django 3.2.19 on 2024-01-11 12:25

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('projects', '0164_attributecategorization'),
    ]

    operations = [
        migrations.AddField(
            model_name='attribute',
            name='error_text',
            field=models.TextField(blank=True, null=True, verbose_name='error text'),
        ),
    ]
