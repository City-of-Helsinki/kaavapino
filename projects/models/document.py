from django.db import models
from django.utils.translation import ugettext_lazy as _

from .project import ProjectPhase


class DocumentTemplate(models.Model):
    name = models.CharField(max_length=255, verbose_name=_('name'))
    project_phase = models.ForeignKey(
        ProjectPhase, verbose_name=_('project phase'), related_name='document_templates', on_delete=models.CASCADE
    )
    file = models.FileField(verbose_name=_('file'))

    class Meta:
        verbose_name = _('document template')
        verbose_name_plural = _('document templates')

    def __str__(self):
        return self.name
