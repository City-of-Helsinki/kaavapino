import datetime
import re
from collections import Sequence, OrderedDict
from html import escape

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.postgres.fields import ArrayField
from django.core.serializers.json import DjangoJSONEncoder
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.utils.translation import gettext_lazy as _

from users.models import User, PRIVILEGE_LEVELS
from .helpers import DATE_SERIALIZATION_FORMAT, validate_identifier
from projects.helpers import get_ad_user
from users.serializers import PersonnelSerializer


class AttributeQuerySet(models.QuerySet):
    def filterable(self):
        return self.filter(
            value_type__in=[
                Attribute.TYPE_INTEGER,
                Attribute.TYPE_DECIMAL,
                Attribute.TYPE_SHORT_STRING,
                Attribute.TYPE_BOOLEAN,
                Attribute.TYPE_DATE,
                Attribute.TYPE_USER,
                Attribute.TYPE_CHOICE,
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
                Attribute.TYPE_RICH_TEXT,
                Attribute.TYPE_RICH_TEXT_SHORT,
                Attribute.TYPE_BOOLEAN,
                Attribute.TYPE_DATE,
                Attribute.TYPE_USER,
                Attribute.TYPE_CHOICE,
            ]
        )


class DataRetentionPlan(models.Model):
    """Defines a data retention plan for an attribute"""

    TYPE_PERMANENT = "permanent"
    TYPE_PROCESSING = "processing"
    TYPE_CUSTOM = "custom"

    TYPE_CHOICES = (
        (TYPE_PERMANENT, _("permanent")),
        (TYPE_PROCESSING, _("while processing")),
        (TYPE_CUSTOM, _("custom duration after archival")),
    )

    UNIT_YEARS = "years"
    UNIT_MONTHS = "months"
    UNIT_DAYS = "days"

    UNIT_CHOICES = (
        (UNIT_YEARS, _("years")),
        (UNIT_MONTHS, _("months")),
        (UNIT_DAYS, _("days")),
    )

    label = models.CharField(max_length=255, verbose_name=_("label"), unique=True)
    plan_type = models.CharField(
        max_length=10,
        verbose_name=_("plan type"),
        choices=TYPE_CHOICES,
    )
    custom_time = models.PositiveIntegerField(
        verbose_name=_("custom time"),
        null=True,
        blank=True,
    )
    custom_time_unit = models.CharField(
        max_length=6,
        verbose_name=_("unit for custom time"),
        choices=UNIT_CHOICES,
        null=True,
        blank=True,
    )

    def __str__(self):
        return self.label


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
    TYPE_RICH_TEXT = "rich_text"
    TYPE_RICH_TEXT_SHORT = "rich_text_short"
    TYPE_BOOLEAN = "boolean"
    TYPE_DATE = "date"
    TYPE_USER = "user"
    TYPE_PERSONNEL = "personnel"
    TYPE_GEOMETRY = "geometry"
    TYPE_IMAGE = "image"
    TYPE_FILE = "file"
    TYPE_LINK = "link"
    TYPE_CHOICE = "choice"

    ALLOWED_CALCULATION_OPERATORS = ["+", "-", "*", "/"]

    TYPE_CHOICES = (
        (TYPE_FIELDSET, _("fieldset")),
        (TYPE_INTEGER, _("integer")),
        (TYPE_DECIMAL, _("decimal")),
        (TYPE_SHORT_STRING, _("short string")),
        (TYPE_LONG_STRING, _("long string")),
        (TYPE_RICH_TEXT, _("rich text")),
        (TYPE_RICH_TEXT_SHORT, _("short rich text")),
        (TYPE_BOOLEAN, _("boolean")),
        (TYPE_DATE, _("date")),
        (TYPE_USER, _("user")),
        (TYPE_PERSONNEL, _("personnel")),
        (TYPE_GEOMETRY, _("geometry")),
        (TYPE_IMAGE, _("image")),
        (TYPE_FILE, _("file")),
        (TYPE_LINK, _("link")),
        (TYPE_CHOICE, _("choice")),
    )

    DISPLAY_DROPDOWN = "dropdown"
    DISPLAY_CHECKBOX = "checkbox"
    DISPLAY_READONLY = "readonly"
    DISPLAY_READONLY_CHECKBOX = "readonly_checkbox"
    DISPLAY_SIMPLE_INTEGER = "simple_integer"

    DISPLAY_CHOICES = (
        (None, _("default")),
        (DISPLAY_DROPDOWN, _("dropdown")),
        (DISPLAY_CHECKBOX, _("checkbox")),
        (DISPLAY_READONLY, _("read only")),
        (DISPLAY_READONLY_CHECKBOX, _("read only checkbox")),
        (DISPLAY_SIMPLE_INTEGER, _("integer without thousand separator")),
    )

    SOURCE_PARENT_FIELDSET = "fieldset"
    SOURCE_FACTA = "/facta/v1/kiinteisto/<pk>/all"
    SOURCE_GEOSERVER = "/geoserver/v1/kiinteisto/<pk>/all"

    SOURCE_CHOICES = (
        (SOURCE_PARENT_FIELDSET, _("Same as parent fieldset")),
        (SOURCE_FACTA, _("FACTA")),
        (SOURCE_GEOSERVER, _("Geoserver")),
    )

    AD_DATA_KEY_ID = "id"
    AD_DATA_KEY_NAME = "name"
    AD_DATA_KEY_PHONE = "phone"
    AD_DATA_KEY_EMAIL = "email"
    AD_DATA_KEY_TITLE = "title"
    AD_DATA_KEY_OFFICE = "office"
    AD_DATA_KEY_COMPANY = "company"

    AD_DATA_KEY_CHOICES = (
        (AD_DATA_KEY_ID, "id"),
        (AD_DATA_KEY_NAME, "name"),
        (AD_DATA_KEY_PHONE, "phone"),
        (AD_DATA_KEY_EMAIL, "email"),
        (AD_DATA_KEY_TITLE, "title"),
        (AD_DATA_KEY_OFFICE, "office"),
        (AD_DATA_KEY_COMPANY, "company"),
    )

    name = models.CharField(max_length=255, verbose_name=_("name"))
    value_type = models.CharField(
        max_length=64, verbose_name=_("value type"), choices=TYPE_CHOICES
    )
    display = models.CharField(
        max_length=64,
        verbose_name=_("display style"),
        choices=DISPLAY_CHOICES,
        default=None,
        null=True,
        blank=True,
    )
    visibility_conditions = ArrayField(
        models.JSONField(
            verbose_name=_("show attribute if any condition applies"),
            default=dict,
            blank=True,
            null=True,
            encoder=DjangoJSONEncoder,
        ),
        verbose_name=_("visibility condition"),
        null=True,
        blank=True,
    )
    hide_conditions = ArrayField(
        models.JSONField(
            verbose_name=_("hide attribute if any condition applies"),
            default=dict,
            blank=True,
            null=True,
            encoder=DjangoJSONEncoder,
        ),
        verbose_name=_("hide condition"),
        null=True,
        blank=True,
    )
    unit = models.CharField(
        max_length=255, verbose_name=_("unit"), null=True, blank=True
    )
    public = models.BooleanField(verbose_name=_("public information"), default=False)
    searchable = models.BooleanField(verbose_name=_("searchable field"), default=False)
    generated = models.BooleanField(verbose_name=_("generated"), default=False)
    data_retention_plan = models.ForeignKey(
        "DataRetentionPlan",
        verbose_name=_("data retention plan"),
        blank=True,
        null=True,
        on_delete=models.PROTECT,
    )
    calculations = ArrayField(
        models.CharField(max_length=255, blank=True), blank=True, null=True
    )
    related_fields = ArrayField(
        models.TextField(blank=True), blank=True, null=True
    )
    required = models.BooleanField(verbose_name=_("required"), default=False)
    multiple_choice = models.BooleanField(
        verbose_name=_("multiple choice"), default=False
    )
    character_limit = models.PositiveIntegerField(
        verbose_name=_("character limit"),
        null=True,
        blank=True,
    )
    placeholder_text = models.TextField(
        verbose_name=_("placeholder text"),
        null=True,
        blank=True,
    )
    unique = models.BooleanField(
        verbose_name=_("unique"),
        default=False,
    )
    error_message = models.TextField(
        verbose_name=_("error message"),
        null=True,
        blank=True,
    )
    identifier = models.CharField(
        max_length=60,
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
    help_link = models.URLField(verbose_name=_("Help link"), blank=True, null=True)
    broadcast_changes = models.BooleanField(default=False)
    autofill_readonly = models.BooleanField(verbose_name=_("read-only autofill field"), null=True)
    autofill_rule = models.JSONField(
        verbose_name=_("autofill rule"),
        default=dict,
        blank=True,
        null=True,
        encoder=DjangoJSONEncoder,
    )
    updates_autofill = models.BooleanField(verbose_name=_("updates related autofill fields"), default=False)
    highlight_group = models.ForeignKey(
        Group,
        verbose_name=_("highlight field for group"),
        on_delete=models.PROTECT,
        null=True,
        blank=True,
    )
    owner_editable = models.BooleanField(
        default=False,
        verbose_name=_("owner can edit"),
    )
    owner_viewable = models.BooleanField(
        default=True,
        verbose_name=_("owner can view"),
    )
    view_privilege = models.CharField(
        verbose_name=_("privilege for viewing"),
        max_length=6,
        choices=PRIVILEGE_LEVELS,
        default="browse",
        null=True,
        blank=True,
    )
    edit_privilege = models.CharField(
        verbose_name=_("privilege for editing"),
        max_length=6,
        choices=PRIVILEGE_LEVELS,
        default=None,
        null=True,
        blank=True,
    )
    # attributes which are linked to static Project fields
    static_property = models.CharField(max_length=255, blank=True, null=True)

    # attributes whose data is fetched from an external source
    data_source = models.CharField(
        max_length=255,
        verbose_name=_("external data source"),
        choices=SOURCE_CHOICES,
        null=True,
        blank=True,
    )
    data_source_key = models.CharField(
        verbose_name=_("field key for external data source"),
        max_length=255,
        null=True,
        blank=True,
    )
    key_attribute = models.ForeignKey(
        "Attribute",
        verbose_name=_("key attribute for fetching external data"),
        related_name="key_for_attributes",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
    )
    key_attribute_path = models.CharField(
        max_length=255,
        null=True,
        blank=True,
    )
    ad_key_attribute = models.ForeignKey(
        "Attribute",
        verbose_name=_("key attribute for fetching AD user data"),
        null=True,
        blank=True,
        on_delete=models.PROTECT,
    )
    ad_data_key = models.CharField(
        verbose_name=_("AD user data key"),
        max_length=7,
        choices=AD_DATA_KEY_CHOICES,
        null=True,
        blank=True,
    )
    objects = AttributeQuerySet.as_manager()

    admin_description = "Projektin kenttien hallinta. Muutokset tänne vaatii mahdollisesti myös muutoksia dokumenttipohjiin."

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
        if not len(self.calculations):
            return

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
        if self.value_type != Attribute.TYPE_FIELDSET \
            and (self.data_source or self.ad_data_key):
            return None

        if self.value_type == Attribute.TYPE_CHOICE:
            value_choices = self.value_choices.all()
        else:
            value_choices = None

        if value_choices and value_choices.exists():
            if self.multiple_choice and value is not None:
                return [v.identifier for v in value]
            else:
                return value.identifier if value else None
        elif self.value_type == Attribute.TYPE_INTEGER:
            if self.multiple_choice and value is not None:
                return [
                    int(v) if v is not None else None
                    for v in value
                ]
            else:
                return int(value) if value is not None else None
        elif self.value_type == Attribute.TYPE_DECIMAL:
            return str(value) if value is not None else None
        elif self.value_type in (
            Attribute.TYPE_SHORT_STRING,
            Attribute.TYPE_LONG_STRING,
            Attribute.TYPE_LINK,
            Attribute.TYPE_CHOICE,
            Attribute.TYPE_PERSONNEL,
        ):
            if self.multiple_choice and value is not None:
                return [
                    str(v) if v else None
                    for v in value
                ]
            else:
                return str(value) if value else None
        elif self.value_type in (
            Attribute.TYPE_RICH_TEXT,
            Attribute.TYPE_RICH_TEXT_SHORT,
        ):
            if self.multiple_choice and value is not None:
                return [v for v in value]
            else:
                return value
        elif self.value_type == Attribute.TYPE_BOOLEAN:
            if self.multiple_choice and value is not None:
                return [
                    bool(v) if v is not None else None
                    for v in value
                ]
            else:
                return bool(value) if value is not None else None
        elif self.value_type == Attribute.TYPE_DATE:
            if isinstance(value, str):
                return value
            return (
                datetime.datetime.strftime(
                    value, DATE_SERIALIZATION_FORMAT
                ) if value else None
            )
        elif self.value_type == Attribute.TYPE_USER:
            # allow saving non-existing users using their names (str) at least for now.
            # actual users are saved using their ids (int).
            if isinstance(value, get_user_model()):
                if self.multiple_choice and value is not None:
                    return [v.uuid for v in value]
                else:
                    return value.uuid
            else:
                if self.multiple_choice and value is not None:
                    return [v or None for v in value]
                else:
                    return value or None
        elif self.value_type == Attribute.TYPE_FIELDSET:
            return self._get_fieldset_serialization(value)
        elif self.value_type in (Attribute.TYPE_FILE, Attribute.TYPE_IMAGE):
            if value is None:
                return None
            else:
                return ""
        else:
            raise Exception('Cannot serialize attribute type "%s".' % self.value_type)

    def deserialize_value(self, value):
        if self.value_type == Attribute.TYPE_CHOICE:
            value_choices = self.value_choices.all()
        else:
            value_choices = None

        if value_choices and value_choices.exists():
            if self.multiple_choice and value is not None:
                return [v for v in value_choices.filter(identifier__in=value)]
            else:
                try:
                    return value_choices.get(identifier=value)
                except AttributeValueChoice.DoesNotExist:
                    return None
        elif self.value_type in (
            Attribute.TYPE_INTEGER,
            Attribute.TYPE_DECIMAL,
            Attribute.TYPE_SHORT_STRING,
            Attribute.TYPE_LONG_STRING,
            Attribute.TYPE_BOOLEAN,
            Attribute.TYPE_LINK,
            Attribute.TYPE_CHOICE,
            Attribute.TYPE_PERSONNEL,
        ):
            return value
        elif self.value_type in (
            Attribute.TYPE_RICH_TEXT,
            Attribute.TYPE_RICH_TEXT_SHORT,
        ):
            return value
        elif self.value_type == Attribute.TYPE_DATE:
            return (
                datetime.datetime.strptime(
                    value, DATE_SERIALIZATION_FORMAT
                ).date() if value else None
            )
        elif self.value_type == Attribute.TYPE_USER:
            try:
                return get_user_model().objects.get(uuid=value)
            except get_user_model().DoesNotExist:
                return None
        elif self.value_type == Attribute.TYPE_FIELDSET:
            return self._get_fieldset_serialization(value, deserialize=True)
        else:
            raise Exception('Cannot deserialize attribute type "%s".' % self.value_type)

    def _get_fieldset_serialization(self, value: Sequence, deserialize: bool = False):
        """Recursively go through the fields in the fieldset and (de)serialize them."""

        if isinstance(value, OrderedDict):
            value = [value]
        elif not isinstance(value, Sequence):
            return None

        entities = []
        fieldset_attributes = self.fieldset_attributes.all()

        for i, listitem in enumerate(value):
            processed_entity = {}
            processed_entity_has_files = False
            for key, val in listitem.items():
                if key == "_deleted":
                    processed_entity[key] = val
                    continue

                for attr in fieldset_attributes:
                    if attr.value_type in (
                        Attribute.TYPE_FILE, Attribute.TYPE_IMAGE
                    ):
                        # TODO If alternate file deletion method is needed,
                        # add if val is None check
                        processed_entity_has_files = True

                    elif attr.identifier == key:
                        if deserialize:
                            processed_value = attr.deserialize_value(
                                val
                            )
                        else:
                            processed_value = attr.serialize_value(val)
                        processed_entity[attr.identifier] = processed_value
                    else:
                        continue

            if processed_entity or processed_entity_has_files:
                entities.append(processed_entity)

        return entities

    def _get_single_display_value(self, value):
        if value is None or self.value_type == Attribute.TYPE_GEOMETRY:
            return None

        if self.value_type in (
            Attribute.TYPE_RICH_TEXT_SHORT,
            Attribute.TYPE_RICH_TEXT,
        ) and value:
            try:
                return ("".join(
                    [item["insert"] for item in value["ops"]]
                ).strip())
            except TypeError:
                return None
        # remove checking type should pinonumero attribute (and possible others) be
        # fixed in the attribute excel
        elif self.value_type == Attribute.TYPE_INTEGER and isinstance(value, int):
            if self.display == Attribute.DISPLAY_SIMPLE_INTEGER:
                return str(value)
            else:
                return '{:,}'.format(value).replace(',', ' ')
        elif self.value_type == Attribute.TYPE_DECIMAL and self.unit in ["ha", "k-m2"]:
            return '{:,}'.format(int(float(value))).replace(',', ' ')
        elif self.value_type == Attribute.TYPE_DATE:
            date_value = datetime.datetime.strptime(value, "%Y-%m-%d")
            return '{d.day}.{d.month}.{d.year}'.format(d=date_value)
        elif self.value_type == Attribute.TYPE_CHOICE:
            try:
                return self.value_choices.get(identifier=value).value
            except AttributeValueChoice.DoesNotExist:
                return value
        elif isinstance(value, bool):
            return "Kyllä" if value else "Ei"
        elif self.value_type == Attribute.TYPE_PERSONNEL:
            try:
                return PersonnelSerializer(get_ad_user(value)).data.get("name")
            except AttributeError:
                return value
        elif self.value_type == Attribute.TYPE_USER:
            if not isinstance(value, User):
                try:
                    user = User.objects.get(uuid=value)
                except ValidationError:
                    return value
            else:
                user = value

            return user.get_full_name()
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


class AttributeAutoValue(models.Model):
    """
    Automatic, dynamic value that gets injected into attribute data based on another
    attribute value

    Differs from autofill rules in that these are not calculated in frontend,
    will update the contents of all projects' fields if database changes are made,
    and will not generate log entries whereas autofill rule based field contents only
    change when frontend sends updated values, and they do generate log entries.
    """

    value_attribute = models.OneToOneField(
        Attribute,
        on_delete=models.CASCADE,
        related_name="automatic_value",
        verbose_name=_("automatic attribute"),
    )
    key_attribute = models.ForeignKey(
        Attribute,
        on_delete=models.CASCADE,
        related_name="automatically_sets",
        verbose_name=_("key attribute"),
    )

    def get_value(self, key):
        key = str(key)
        try:
            return self.value_map.get(key_str=key).value
        except AttributeAutoValueMapping.DoesNotExist:
            return None

    def __str__(self):
        return f"{self.key_attribute.name} -> {self.value_attribute.name}"

    admin_description = "Kentät joiden arvo määräytyy toisen kentän arvon perusteella"

    class Meta:
        verbose_name = _("attribute auto value map")
        verbose_name_plural = _("attribute auto value maps")


class AttributeAutoValueMapping(models.Model):
    """A single key-value pair related to an auto value attribute pair"""
    auto_attr = models.ForeignKey(
        AttributeAutoValue,
        on_delete=models.CASCADE,
        related_name="value_map",
        verbose_name=_("attribute link"),
    )
    key_str = models.TextField(verbose_name=_("key"))
    value_str = models.TextField(verbose_name=_("value"))

    @property
    def key(self):
        return self.auto_attr.key_attribute.deserialize_value(self.key_str)

    @property
    def value(self):
        return self.auto_attr.value_attribute.deserialize_value(self.value_str)

    class Meta:
        unique_together = ('auto_attr', 'key_str')
        verbose_name = _("attribute auto value mapping")
        verbose_name_plural = _("attribute auto value mappings")


class FieldSetAttribute(models.Model):

    attribute_source = models.ForeignKey(
        Attribute, on_delete=models.CASCADE, related_name="fieldset_attribute_source"
    )
    attribute_target = models.ForeignKey(
        Attribute, on_delete=models.CASCADE, related_name="fieldset_attribute_target"
    )
    phase_indices = models.ManyToManyField(
        "ProjectPhase",
        symmetrical=False,
        related_name="fieldsets",
        through="ProjectPhaseFieldSetAttributeIndex",
    )

    class Meta:
        verbose_name = _("fieldset attribute")
        verbose_name_plural = _("fieldset attributes")

    def __str__(self):
        return f"{self.attribute_source} -> {self.attribute_target}"


class DocumentLinkSection(models.Model):
    """Defines a project card document link subsection"""
    name = models.CharField(
        max_length=255,
        verbose_name=_("name"),
    )
    index = models.PositiveIntegerField(
        verbose_name=_("index"),
        default=0,
    )

    class Meta:
        verbose_name = _("document link section")
        verbose_name_plural = _("document link sections")
        ordering = ("index",)

    def __str__(self):
        return f"{self.name}"


class DocumentLinkFieldSet(models.Model):
    """Connects external document link and name within a fieldset"""
    section = models.ForeignKey(
        DocumentLinkSection,
        on_delete=models.CASCADE,
    )
    fieldset_attribute = models.ForeignKey(
        Attribute,
        on_delete=models.CASCADE,
        related_name="document_fieldsets",
        verbose_name=_("fieldset attribute"),
    )
    document_name_attribute = models.ForeignKey(
        Attribute,
        on_delete=models.CASCADE,
        related_name="name_in_document_fieldsets",
        verbose_name=_("document name attribute"),
        null=True,
        blank=True,
    )
    document_custom_name_attribute = models.ForeignKey(
        Attribute,
        on_delete=models.CASCADE,
        related_name="custom_name_in_document_fieldsets",
        verbose_name=_("document custom name attribute"),
        null=True,
        blank=True,
    )
    document_link_attribute = models.ForeignKey(
        Attribute,
        on_delete=models.CASCADE,
        related_name="link_in_document_fieldsets",
        verbose_name=_("document link attribute"),
    )

    class Meta:
        verbose_name = _("document link fieldset")
        verbose_name_plural = _("document link fieldsets")

    def __str__(self):
        return f"{self.fieldset_attribute.name}"


class OverviewFilter(models.Model):
    """Defines a filter on project overview views"""
    name = models.CharField(
        max_length=255,
        verbose_name=_("name"),
    )
    identifier = models.CharField(
        max_length=20,
        verbose_name=_("identifier"),
        db_index=True,
        unique=True,
        validators=[validate_identifier],
    )

    admin_description = "Karttanäkymän suodattimet"

    class Meta:
        verbose_name = _("overview filter")
        verbose_name_plural = _("overview filters")

    def __str__(self):
        return f"{self.name}"


class OverviewFilterAttribute(models.Model):
    """Defines an attribute in a filter"""
    attribute = models.ForeignKey(
        Attribute,
        on_delete=models.CASCADE,
        verbose_name=_("attribute"),
    )
    overview_filter = models.ForeignKey(
        OverviewFilter,
        on_delete=models.CASCADE,
        verbose_name=_("overview filter"),
        related_name="attributes",
    )
    filters_by_subtype = models.BooleanField(
        verbose_name=_("filters project subtype overview"),
        default=False,
    )
    filters_floor_area = models.BooleanField(
        verbose_name=_("filters project floor area overview"),
        default=False,
    )
    filters_on_map = models.BooleanField(
        verbose_name=_("filters project map overview"),
        default=False,
    )

    class Meta:
        verbose_name = _("overview filter attribute")
        verbose_name_plural = _("overview filter attributes")

    def __str__(self):
        return f"{self.overview_filter.name}/{self.attribute.name}"
