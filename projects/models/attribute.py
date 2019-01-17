import datetime
import re
from collections import Sequence
from html import escape

from django.contrib.auth import get_user_model
from django.contrib.postgres.fields import ArrayField
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.db import models, transaction
from django.utils.translation import ugettext_lazy as _

from users.models import User

DATE_SERIALIZATION_FORMAT = "%Y-%m-%d"

identifier_re = re.compile(r"^[\w]+\Z")

validate_identifier = RegexValidator(
    identifier_re,
    _(
        "Enter a valid 'identifier' consisting of Unicode letters, numbers or underscores."
    ),
    "invalid",
)


class AttributeQuerySet(models.QuerySet):
    def filterable(self):
        return self.filter(
            value_type__in=[
                # Attribute.TYPE_FIELDSET,
                Attribute.TYPE_INTEGER,
                Attribute.TYPE_DECIMAL,
                Attribute.TYPE_SHORT_STRING,
                # Attribute.TYPE_LONG_STRING,
                Attribute.TYPE_BOOLEAN,
                Attribute.TYPE_DATE,
                Attribute.TYPE_USER,
            ]
        )

    def report_friendly(self):
        return self.filter(
            value_type__in=[
                Attribute.TYPE_FIELDSET,
                Attribute.TYPE_INTEGER,
                Attribute.TYPE_DECIMAL,
                Attribute.TYPE_SHORT_STRING,
                Attribute.TYPE_LONG_STRING,
                Attribute.TYPE_BOOLEAN,
                Attribute.TYPE_DATE,
                Attribute.TYPE_USER,
            ]
        )


class Attribute(models.Model):
    """Defines a single attribute type.

    Fieldset defines a group of tightly related attributes that define a single entity. E.g. information regarding
    a person might consist of several fields. If there is a need to store information for multiple entities, we
    can define a fieldset which knows the attributes for a single entity.
    """

    TYPE_FIELDSET = "fieldset"
    TYPE_INTEGER = "integer"
    TYPE_DECIMAL = "decimal"
    TYPE_SHORT_STRING = "short_string"
    TYPE_LONG_STRING = "long_string"
    TYPE_BOOLEAN = "boolean"
    TYPE_DATE = "date"
    TYPE_USER = "user"
    TYPE_GEOMETRY = "geometry"
    TYPE_IMAGE = "image"
    TYPE_FILE = "file"
    TYPE_LINK = "link"

    ALLOWED_CALCULATION_OPERATORS = ["+", "-", "*", "/"]

    TYPE_CHOICES = (
        (TYPE_FIELDSET, _("fieldset")),
        (TYPE_INTEGER, _("integer")),
        (TYPE_DECIMAL, _("decimal")),
        (TYPE_SHORT_STRING, _("short string")),
        (TYPE_LONG_STRING, _("long string")),
        (TYPE_BOOLEAN, _("boolean")),
        (TYPE_DATE, _("date")),
        (TYPE_USER, _("user")),
        (TYPE_GEOMETRY, _("geometry")),
        (TYPE_IMAGE, _("image")),
        (TYPE_FILE, _("file")),
        (TYPE_LINK, _("link")),
    )

    name = models.CharField(max_length=255, verbose_name=_("name"))
    value_type = models.CharField(
        max_length=64, verbose_name=_("value type"), choices=TYPE_CHOICES
    )
    public = models.BooleanField(verbose_name=_("public information"), default=False)
    generated = models.BooleanField(verbose_name=_("generated"), default=False)
    calculations = ArrayField(
        models.CharField(max_length=255, blank=True), blank=True, null=True
    )
    required = models.BooleanField(verbose_name=_("required"), default=False)
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
    fieldset_attributes = models.ManyToManyField(
        "self",
        symmetrical=False,
        related_name="fieldsets",
        through="FieldSetAttribute",
        through_fields=("attribute_source", "attribute_target"),
    )
    help_text = models.TextField(verbose_name=_("Help text"), blank=True)

    objects = AttributeQuerySet.as_manager()

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

    def clean(self):
        # Only allow for uneven arrays
        if len(self.calculations) % 2 != 1:
            raise ValidationError(
                f"Calculations needs to be uneven in length and"
                f"follow the style '(<attribtute> <operator> <attribute>)*n. "
                f"Error in {self.identifier} with calculations {self.calculations}."
            )

        if self.calculations[-1] in self.ALLOWED_CALCULATION_OPERATORS:
            raise ValidationError(
                f"Calculation can not end with operator. "
                f"Error in {self.identifier} with calculations {self.calculations}."
            )

        if not all(
            operator in self.ALLOWED_CALCULATION_OPERATORS
            for operator in self.calculation_operators
        ):
            raise ValidationError(
                f"Calculation operators can only be {self.ALLOWED_CALCULATION_OPERATORS}. "
                f"Error in {self.identifier} with calculation {self.calculations}."
            )

        if (
            len(self.calculation_operators)
            != len(self.calculation_attribute_identifiers) - 1
        ):
            raise ValidationError(
                f"There must be exactly one more attribute then operators"
                f"Error in {self.identifier} with calculation {self.calculations}."
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
        elif self.value_type == Attribute.TYPE_DECIMAL:
            return float(value) if value is not None else None
        elif self.value_type in (
            Attribute.TYPE_SHORT_STRING,
            Attribute.TYPE_LONG_STRING,
            Attribute.TYPE_LINK,
        ):
            return str(value) if value else None
        elif self.value_type == Attribute.TYPE_BOOLEAN:
            return bool(value) if value is not None else None
        elif self.value_type == Attribute.TYPE_DATE:
            return value.strftime(DATE_SERIALIZATION_FORMAT) if value else None
        elif self.value_type == Attribute.TYPE_USER:
            # allow saving non-existing users using their names (str) at least for now.
            # actual users are saved using their ids (int).
            if isinstance(value, get_user_model()):
                return value.uuid
            else:
                return value or None
        elif self.value_type == Attribute.TYPE_FIELDSET:
            return self._get_fieldset_serialization(value)
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
            Attribute.TYPE_DECIMAL,
            Attribute.TYPE_SHORT_STRING,
            Attribute.TYPE_LONG_STRING,
            Attribute.TYPE_BOOLEAN,
            Attribute.TYPE_LINK,
        ):
            return value
        elif self.value_type == Attribute.TYPE_DATE:
            return (
                datetime.datetime.strptime(value, DATE_SERIALIZATION_FORMAT)
                if value
                else None
            )
        elif self.value_type == Attribute.TYPE_USER:
            return get_user_model().objects.get(uuid=value)
        elif self.value_type == Attribute.TYPE_FIELDSET:
            return self._get_fieldset_serialization(value, deserialize=True)
        else:
            raise Exception('Cannot deserialize attribute type "%s".' % self.value_type)

    def _get_fieldset_serialization(self, value: Sequence, deserialize: bool = False):
        """Recursively go through the fields in the fieldset and (de)serialize them."""
        if not isinstance(value, Sequence):
            return None

        entities = []
        fieldset_attributes = self.fieldset_attributes.all()
        for entity in value:
            processed_entity = {}
            for attr in fieldset_attributes:
                if attr.identifier in entity:
                    if deserialize:
                        processed_value = attr.deserialize_value(
                            entity[attr.identifier]
                        )
                    else:
                        processed_value = attr.serialize_value(entity[attr.identifier])
                    processed_entity[attr.identifier] = processed_value
            if processed_entity:
                entities.append(processed_entity)
        return entities

    def _get_single_display_value(self, value):
        if value is None or self.value_type == Attribute.TYPE_GEOMETRY:
            return None
        if isinstance(self.value_type, bool):
            return "Kyllä" if value else "Ei"
        elif isinstance(self.value_type, datetime.date):
            return value.strftime("%d.%m.%Y")
        elif isinstance(value, User):
            return value.get_full_name()
        else:
            return escape(str(value))

    def get_attribute_display(self, value):
        if isinstance(value, list):
            if self.value_type == Attribute.TYPE_FIELDSET:
                return [
                    {k: self._get_single_display_value(v) for k, v in item.items()}
                    for item in value
                ]
            return [self._get_single_display_value(v) for v in value]
        else:
            return self._get_single_display_value(value)

    @property
    def calculation_attribute_identifiers(self):
        if not self.calculations:
            return []
        return self.calculations[0::2]

    @property
    def calculation_operators(self):
        if not self.calculations:
            return []
        return self.calculations[1::2]


class AttributeValueChoice(models.Model):
    """Single value choice for a single attribute."""

    attribute = models.ForeignKey(
        Attribute,
        verbose_name=_("attribute"),
        related_name="value_choices",
        on_delete=models.CASCADE,
    )
    value = models.TextField(verbose_name=_("value"))
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


class FieldSetAttribute(models.Model):

    attribute_source = models.ForeignKey(
        Attribute, on_delete=models.CASCADE, related_name="fieldset_attribute_source"
    )
    attribute_target = models.ForeignKey(
        Attribute, on_delete=models.CASCADE, related_name="fieldset_attribute_target"
    )
    index = models.PositiveIntegerField(verbose_name=_("index"), default=0)

    class Meta:
        verbose_name = _("fieldset attribute")
        verbose_name_plural = _("fieldset attributes")
        ordering = ("index",)

    def __str__(self):
        return f"{self.attribute_source} -> {self.attribute_target}"
