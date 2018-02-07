from django.conf import settings
from django.contrib.gis.db import models
from django.contrib.postgres.fields import JSONField
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
    user = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name=_('user'), related_name='projects', null=True,
                             blank=True, on_delete=models.PROTECT)
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

    def get_attribute_data(self):
        ret = {}

        for attribute in Attribute.objects.all().prefetch_related('value_choices'):
            deserialized_value = None

            if attribute.value_type == Attribute.TYPE_GEOMETRY:
                deserialized_value = self.geometry
            elif attribute.identifier in self.attribute_data:
                deserialized_value = attribute.deserialize_value(self.attribute_data[attribute.identifier])
            elif attribute.value_type == Attribute.TYPE_IMAGE:
                try:
                    deserialized_value = ProjectAttributeImage.objects.get(
                        attribute=attribute,
                        project=self,
                    ).image
                except ProjectAttributeImage.DoesNotExist:
                    deserialized_value = None

            ret[attribute.identifier] = deserialized_value
        return ret

    def set_attribute_data(self, data):
        self.attribute_data = {}
        self.geometry = None
        self.update_attribute_data(data)

    def update_attribute_data(self, data):
        attributes = {a.identifier: a for a in Attribute.objects.all().prefetch_related('value_choices')}

        for identifier, value in data.items():
            attribute = attributes.get(identifier)

            if not attribute:
                continue

            if attribute.value_type == Attribute.TYPE_GEOMETRY:
                self.geometry = value
            elif attribute.value_type == Attribute.TYPE_IMAGE:
                if value is False:
                    ProjectAttributeImage.objects.filter(attribute=attribute, project=self).delete()
                elif value is None:
                    # None is handled in the same way as omitting this attribute from the update in the first place
                    # would have been, ie. do nothing. This is to make life easier as the form where these images
                    # mainly come from uses False for "delete" and None for "no update".
                    continue
                else:
                    ProjectAttributeImage.objects.update_or_create(
                        attribute=attribute,
                        project=self,
                        defaults={'image': value}
                    )
            else:
                serialized_value = attribute.serialize_value(value)

                if serialized_value is not None:
                    self.attribute_data[identifier] = serialized_value
                else:
                    self.attribute_data.pop(identifier, None)


class ProjectPhase(models.Model):
    project_type = models.ForeignKey(ProjectType, verbose_name=_('project type'), on_delete=models.CASCADE,
                                     related_name='phases')
    name = models.CharField(max_length=255, verbose_name=_('name'))
    color = models.CharField(max_length=64, verbose_name=_('color'), blank=True)
    color_code = models.CharField(max_length=10, verbose_name=_('color code'), blank=True)
    index = models.PositiveIntegerField(verbose_name=_('index'), default=0)

    class Meta:
        verbose_name = _('project phase')
        verbose_name_plural = _('project phases')
        unique_together = ('project_type', 'index')
        ordering = ('project_type', 'index',)

    def __str__(self):
        return self.name


class ProjectPhaseSection(models.Model):
    phase = models.ForeignKey(ProjectPhase, verbose_name=_('phase'), related_name='sections', on_delete=models.CASCADE)
    name = models.CharField(max_length=255, verbose_name=_('name'))
    index = models.PositiveIntegerField(verbose_name=_('index'), default=0)
    attributes = models.ManyToManyField(
        Attribute, verbose_name=_('attributes'), related_name='phase_sections', through='ProjectPhaseSectionAttribute'
    )

    class Meta:
        verbose_name = _('project phase section')
        verbose_name_plural = _('project phase sections')
        unique_together = ('phase', 'index')
        ordering = ('phase', 'index')

    def __str__(self):
        return self.name

    def get_attribute_identifiers(self):
        return [a.identifier for a in self.attributes.all()]


class ProjectPhaseSectionAttribute(models.Model):
    attribute = models.ForeignKey(Attribute, verbose_name=_('attribute'), on_delete=models.CASCADE)
    section = models.ForeignKey(ProjectPhaseSection, verbose_name=_('phase section'), on_delete=models.CASCADE)
    generated = models.BooleanField(verbose_name=_('generated'), default=False)
    required = models.BooleanField(verbose_name=_('required'))
    index = models.PositiveIntegerField(verbose_name=_('index'), default=0)

    class Meta:
        verbose_name = _('project phase section attribute')
        verbose_name_plural = _('project phase section attributes')
        unique_together = ('section', 'index')
        ordering = ('section', 'index')

    def __str__(self):
        return '{} {} {} {}'.format(self.attribute, self.section, self.section.phase, self.index)


class ProjectAttributeImage(models.Model):
    attribute = models.ForeignKey(Attribute, verbose_name=_('attribute'), related_name='images',
                                  on_delete=models.CASCADE)
    project = models.ForeignKey(Project, verbose_name=_('project'), related_name='images', on_delete=models.CASCADE)
    image = models.ImageField(verbose_name=_('image'))

    class Meta:
        verbose_name = _('project attribute image')
        verbose_name_plural = _('project attribute images')

    def __str__(self):
        return '{} {}'.format(self.project, self.attribute)
