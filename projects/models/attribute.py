import datetime
import re

from django.contrib.auth import get_user_model
from django.core.validators import RegexValidator
from django.db import models, transaction
from django.utils.translation import ugettext_lazy as _

DATE_SERIALIZATION_FORMAT = "%Y-%m-%d"

identifier_re = re.compile(r"^[\w]+\Z")

validate_identifier = RegexValidator(
    identifier_re,
    _(
        "Enter a valid 'identifier' consisting of Unicode letters, numbers or underscores."
    ),
    "invalid",
)


class Attribute(models.Model):
    """Defines a single attribute type."""

    TYPE_INTEGER = "integer"
    TYPE_SHORT_STRING = "short_string"
    TYPE_LONG_STRING = "long_string"
    TYPE_BOOLEAN = "boolean"
    TYPE_DATE = "date"
    TYPE_USER = "user"
    TYPE_GEOMETRY = "geometry"
    TYPE_IMAGE = "image"
    TYPE_FILE = "file"

    TYPE_CHOICES = (
        (TYPE_INTEGER, _("integer")),
        (TYPE_SHORT_STRING, _("short string")),
        (TYPE_LONG_STRING, _("long string")),
        (TYPE_BOOLEAN, _("boolean")),
        (TYPE_DATE, _("date")),
        (TYPE_USER, _("user")),
        (TYPE_GEOMETRY, _("geometry")),
        (TYPE_IMAGE, _("image")),
        (TYPE_FILE, _("file")),
    )

    name = models.CharField(max_length=255, verbose_name=_("name"))
    value_type = models.CharField(
        max_length=64, verbose_name=_("value type"), choices=TYPE_CHOICES
    )
    public = models.BooleanField(verbose_name=_("public information"), default=False)
    multiple_choice = models.BooleanField(
        verbose_name=_("multiple choice"), default=False
    )
    identifier = models.CharField(
        max_length=50,
        verbose_name=_("identifier"),
        db_index=True,
        unique=True,
        validators=[validate_identifier],
    )
    help_text = models.TextField(verbose_name=_("Help text"), blank=True)

    class Meta:
        verbose_name = _("attribute")
        verbose_name_plural = _("attributes")
        ordering = ("identifier",)

    def __str__(self):
        return f"{self.name} ({self.value_type})"

    @transaction.atomic
    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)

        if self.value_type == Attribute.TYPE_GEOMETRY:
            if (
                Attribute.objects.exclude(id=self.id)
                .filter(value_type=Attribute.TYPE_GEOMETRY)
                .exists()
            ):
                raise NotImplementedError(
                    "Currently only one geometry type attribute at a time is supported."
                )

    def serialize_value(self, value):
        value_choices = self.value_choices.all()

        if value_choices.exists():
            if self.multiple_choice:
                return [v.identifier for v in value]
            else:
                return value.identifier if value else None
        elif self.value_type == Attribute.TYPE_INTEGER:
            return int(value) if value is not None else None
        elif self.value_type in (
            Attribute.TYPE_SHORT_STRING,
            Attribute.TYPE_LONG_STRING,
        ):
            return str(value) if value else None
        elif self.value_type == Attribute.TYPE_BOOLEAN:
            return bool(value)
        elif self.value_type == Attribute.TYPE_DATE:
            return value.strftime(DATE_SERIALIZATION_FORMAT) if value else None
        elif self.value_type == Attribute.TYPE_USER:
            # allow saving non-existing users using their names (str) at least for now.
            # actual users are saved using their ids (int).
            if isinstance(value, get_user_model()):
                return value.uuid
            else:
                return value or None
        else:
            raise Exception('Cannot serialize attribute type "%s".' % self.value_type)

    def deserialize_value(self, value):
        value_choices = self.value_choices.all()

        if value_choices.exists():
            if self.multiple_choice:
                return [v for v in value_choices.filter(identifier__in=value)]
            else:
                return value_choices.get(identifier=value)
        elif self.value_type in (
            Attribute.TYPE_INTEGER,
            Attribute.TYPE_SHORT_STRING,
            Attribute.TYPE_LONG_STRING,
            Attribute.TYPE_BOOLEAN,
        ):
            return value
        elif self.value_type == Attribute.TYPE_DATE:
            return (
                datetime.datetime.strptime(value, DATE_SERIALIZATION_FORMAT)
                if value
                else None
            )
        elif self.value_type == Attribute.TYPE_USER:
            if isinstance(value, str):
                return value
            else:
                return get_user_model().objects.get(id=value)
        else:
            raise Exception('Cannot deserialize attribute type "%s".' % self.value_type)


class AttributeValueChoice(models.Model):
    """Single value choice for a single attribute."""

    attribute = models.ForeignKey(
        Attribute,
        verbose_name=_("attribute"),
        related_name="value_choices",
        on_delete=models.CASCADE,
    )
    value = models.CharField(max_length=255, verbose_name=_("value"))
    identifier = models.CharField(
        max_length=150,
        verbose_name=_("identifier"),
        db_index=True,
        validators=[validate_identifier],
    )
    index = models.PositiveIntegerField(verbose_name=_("index"), default=0)

    class Meta:
        verbose_name = _("attribute value choice")
        verbose_name_plural = _("attribute value choices")
        unique_together = (("attribute", "identifier"), ("attribute", "index"))
        ordering = ("index",)

    def __str__(self):
        return self.value
