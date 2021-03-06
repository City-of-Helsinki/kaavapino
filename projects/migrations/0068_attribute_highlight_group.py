# Generated by Django 2.2.13 on 2020-10-01 11:55

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('auth', '0011_update_proxy_permissions'),
        ('projects', '0067_data_retention_plan'),
    ]

    operations = [
        migrations.AddField(
            model_name='attribute',
            name='highlight_group',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, to='auth.Group', verbose_name='highlight field for group'),
        ),
        migrations.AlterField(
            model_name='attribute',
            name='display',
            field=models.CharField(blank=True, choices=[(None, 'default'), ('dropdown', 'dropdown')], default=None, max_length=64, null=True, verbose_name='display style'),
        ),
    ]
