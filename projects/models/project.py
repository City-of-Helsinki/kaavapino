from django.contrib.postgres.fields import JSONField
from django.contrib.gis.db import models
from django.utils.translation import ugettext_lazy as _

from .attribute import Attribute


class ProjectType(models.Model):
    name = models.CharField(max_length=255, verbose_name=_('name'))

    class Meta:
        verbose_name = _('project type')
        verbose_name_plural = _('project types')
        ordering = ('name',)

    def __str__(self):
        return self.name


class Project(models.Model):
    created_at = models.DateTimeField(verbose_name=_('created at'), auto_now_add=True, editable=False)
    modified_at = models.DateTimeField(verbose_name=_('modified at'), auto_now=True, editable=False)
    name = models.CharField(max_length=255, verbose_name=_('name'))
    identifier = models.CharField(max_length=50, verbose_name=_('identifier'), db_index=True, blank=True, null=True)
    type = models.ForeignKey(ProjectType, verbose_name=_('type'), related_name='projects', on_delete=models.PROTECT)
    attribute_data = JSONField(verbose_name=_('attribute data'), default=dict, blank=True, null=True)
    phase = models.ForeignKey('ProjectPhase', verbose_name=_('phase'), null=True, related_name='projects',
                              on_delete=models.PROTECT)

    geometry = models.MultiPolygonField(null=True, blank=True)

    class Meta:
        verbose_name = _('project')
        verbose_name_plural = _('projects')
        ordering = ('id',)

    def __str__(self):
        return self.name


class ProjectPhase(models.Model):
    project_type = models.ForeignKey(ProjectType, verbose_name=_('project type'), on_delete=models.CASCADE,
                                     related_name='phases')
    name = models.CharField(max_length=255, verbose_name=_('name'))
    color = models.CharField(max_length=64, verbose_name=_('color'), blank=True)
    index = models.PositiveIntegerField(verbose_name=_('index'), null=True, blank=True)
    attributes = models.ManyToManyField(
        Attribute, verbose_name=_('attributes'), related_name='project_phases', through='ProjectPhaseAttribute'
    )

    class Meta:
        verbose_name = _('project phase')
        verbose_name_plural = _('project phases')
        unique_together = ('project_type', 'index')
        ordering = ('project_type', 'index',)

    def __str__(self):
        return self.name


class ProjectPhaseAttribute(models.Model):
    attribute = models.ForeignKey(Attribute, verbose_name=_('attribute'), on_delete=models.CASCADE)
    phase = models.ForeignKey(ProjectPhase, verbose_name=_('phase'), on_delete=models.CASCADE)
    required = models.BooleanField(verbose_name=_('required'))
    index = models.PositiveIntegerField(verbose_name=_('index'), null=True, blank=True)

    class Meta:
        verbose_name = _('project phase attribute')
        verbose_name_plural = _('project phase attributes')

    def __str__(self):
        return '{} {} {}'.format(self.attribute, self.phase, self.index)
