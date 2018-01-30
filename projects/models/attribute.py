import re

from django.core.validators import RegexValidator
from django.db import models
from django.utils.translation import ugettext_lazy as _

identifier_re = re.compile(r'^[\w]+\Z')

validate_identifier = RegexValidator(
    identifier_re,
    _("Enter a valid 'identifier' consisting of Unicode letters, numbers or underscores."),
    'invalid'
)


class Attribute(models.Model):
    TYPE_INTEGER = 'integer'
    TYPE_SHORT_STRING = 'short_string'
    TYPE_LONG_STRING = 'long_string'
    TYPE_BOOLEAN = 'boolean'
    TYPE_DATE = 'date'
    TYPE_USER = 'user'

    TYPE_CHOICES = (
        (TYPE_INTEGER, _('integer')),
        (TYPE_SHORT_STRING, _('short string')),
        (TYPE_LONG_STRING, _('long string')),
        (TYPE_BOOLEAN, _('boolean')),
        (TYPE_DATE, _('date')),
        (TYPE_USER, _('user')),
    )

    name = models.CharField(max_length=255, verbose_name=_('name'))
    value_type = models.CharField(max_length=64, verbose_name=_('value type'), choices=TYPE_CHOICES)
    multiple_choice = models.BooleanField(verbose_name=_('multiple choice'), default=False)
    identifier = models.CharField(
        max_length=50, verbose_name=_('identifier'), db_index=True, unique=True, validators=[validate_identifier]
    )

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
    identifier = models.CharField(
        max_length=150, verbose_name=_('identifier'), db_index=True, validators=[validate_identifier]
    )
    index = models.PositiveIntegerField(verbose_name=_('index'), default=0)

    class Meta:
        verbose_name = _('attribute value choice')
        verbose_name_plural = _('attribute value choices')
        unique_together = (('attribute', 'identifier'), ('attribute', 'index'))
        ordering = ('index',)

    def __str__(self):
        return self.value
