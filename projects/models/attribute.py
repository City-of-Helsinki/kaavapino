from django.db import models
from django.utils.translation import ugettext_lazy as _


class Attribute(models.Model):
    TYPE_INT = 'int'
    TYPE_STRING = 'string'
    TYPE_BOOLEAN = 'boolean'
    TYPE_DATE = 'date'
    TYPE_CHOICES = (
        (TYPE_INT, _('int')),
        (TYPE_STRING, _('string')),
        (TYPE_BOOLEAN, _('boolean')),
        (TYPE_DATE, _('date')),
    )

    name = models.CharField(max_length=255, verbose_name=_('name'))
    value_type = models.CharField(max_length=64, verbose_name=_('value type'), choices=TYPE_CHOICES)
    slug = models.SlugField(verbose_name=_('slug'), db_index=True, unique=True)

    class Meta:
        verbose_name = _('attribute')
        verbose_name_plural = _('attributes')

    def __str__(self):
        return '{} ({})'.format(self.name, self.value_type)


class AttributeValueChoice(models.Model):
    attribute = models.ForeignKey(
        Attribute, verbose_name=_('attribute'), related_name='value_choices', on_delete=models.CASCADE
    )
    value = models.CharField(max_length=255, verbose_name=_('value'))
    slug = models.SlugField(verbose_name=_('slug'), db_index=True)

    class Meta:
        verbose_name = _('attribute value choice')
        verbose_name_plural = _('attribute value choices')
        unique_together = ('attribute', 'slug')

    def __str__(self):
        return self.value
