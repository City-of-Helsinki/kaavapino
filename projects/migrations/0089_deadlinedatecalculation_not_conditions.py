# Generated by Django 2.2.13 on 2020-12-07 08:39

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('projects', '0088_attribute_identifier_max_length'),
    ]

    operations = [
        migrations.AddField(
            model_name='deadlinedatecalculation',
            name='not_conditions',
            field=models.ManyToManyField(blank=True, related_name='not_condition_for_deadlinedatecalculation', to='projects.Attribute', verbose_name='use rule if any attribute is falsy'),
        ),
        migrations.AlterField(
            model_name='deadlinedatecalculation',
            name='conditions',
            field=models.ManyToManyField(blank=True, related_name='condition_for_deadlinedatecalculation', to='projects.Attribute', verbose_name='use rule if any attribute is truthy'),
        ),
    ]
