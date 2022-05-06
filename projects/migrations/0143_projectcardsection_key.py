# Generated by Django 3.2.10 on 2022-05-06 07:40

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('projects', '0142_auto_20220421_1222'),
    ]

    operations = [
        migrations.AddField(
            model_name='projectcardsection',
            name='key',
            field=models.CharField(choices=[('projektikortin_kuva', 'projektikortin_kuva'), ('perustiedot', 'perustiedot'), ('suunnittelualueen_kuvaus', 'suunnittelualueen_kuvaus'), ('strategiakytkenta', 'strategiakytkenta'), ('maanomistus', 'maanomistus'), ('kerrosalatiedot', 'kerrosalatiedot'), ('aikataulu', 'aikataulu'), ('yhteyshenkilöt', 'yhteyshenkilöt'), ('dokumentit', 'dokumentit'), ('suunnittelualueen_rajaus', 'suunnittelualueen_rajaus')], max_length=255, null=True, verbose_name='key'),
        ),
    ]
