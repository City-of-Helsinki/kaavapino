import os

from django.db.models.signals import pre_delete
from django.dispatch import receiver

from projects.models import ProjectAttributeFile


@receiver(pre_delete, sender=ProjectAttributeFile)
def delete_file_pre_delete_post(sender, instance, *args, **kwargs):
    if instance.file:
        path = instance.file.path
        if os.path.isfile(path):
            os.remove(path)
