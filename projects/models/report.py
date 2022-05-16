import re
from datetime import datetime

from django.contrib.gis.db import models
from django.db.models import JSONField, Q
from django.db.models.functions import Cast
from django.db.models.fields.related import ForeignKey
from django.utils.translation import gettext_lazy as _
from django.contrib.auth import get_user_model
from django.contrib.postgres.fields.jsonb import KeyTextTransform
from django.core.serializers.json import DjangoJSONEncoder

from projects.helpers import get_fieldset_path
from projects.models import (
    Attribute,
    Project,
    ProjectSubtype,
    AttributeValueChoice,
)


class Report(models.Model):
    project_type = models.ForeignKey(
        "ProjectType",
        verbose_name=_("project type"),
        on_delete=models.CASCADE,
        related_name="reports",
    )

    name = models.CharField(max_length=255, verbose_name=_("name"))
    is_admin_report = models.BooleanField(
        verbose_name=_("can only be fetched by admin"), default=False
    )
    show_created_at = models.BooleanField(
        verbose_name=_("show created at on report"), default=False
    )
    show_modified_at = models.BooleanField(
        verbose_name=_("show modified at on report"), default=False
    )
    previewable = models.BooleanField(
        verbose_name=_("report can be previewed"), default=False
    )
    hidden = models.BooleanField(
        verbose_name=_("hide report from other views"), default=False
    )

    class Meta:
        verbose_name = _("report")
        verbose_name_plural = _("reports")
        ordering = ("id",)

    def __str__(self):
        return f"{self.name}"

    @property
    def filters(self):
        return Attribute.objects.filterable().filter(report_attributes__report=self)


class ReportColumn(models.Model):
    report = models.ForeignKey(
        Report,
        verbose_name=_("report"),
        on_delete=models.CASCADE,
        related_name="columns",
    )
    title = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        verbose_name=_("title"),
    )
    attributes = models.ManyToManyField(
        Attribute,
        verbose_name=_("attributes"),
        related_name="report_columns",
    )
    condition = models.ManyToManyField(
        Attribute,
        verbose_name=_("condition"),
        related_name="report_column_conditions",
        blank=True,
    )
    index = models.PositiveIntegerField(
        verbose_name=_("index"),
        default=0,
    )
    postfix_only = models.BooleanField(
        verbose_name=_("only show postfix as field value"),
        default=False,
    )
    preview = models.BooleanField(
        verbose_name=_("include in preview"),
        default=True,
    )
    preview_only = models.BooleanField(
        verbose_name=_("only show in preview"),
        default=False,
    )
    preview_title_column = models.BooleanField(
        verbose_name=_("use column values as titles in preview"),
        default=False,
    )
    custom_display_mapping = models.JSONField(
        default=dict,
        blank=True,
        null=True,
        encoder=DjangoJSONEncoder,
        verbose_name=_("map automatic display value strings to custom display values"),
    )
    generates_new_rows = models.BooleanField(
        default=False,
        verbose_name=_("create new column"),
    )

    def generate_postfix(self, project, attribute_data=None):
        postfixes = self.postfixes.filter(
            subtypes__in=[project.subtype],
        )
        postfix = None

        if not postfixes.count():
            return ""

        # Fallback doesn't include data from external APIs
        attribute_data = attribute_data or project.attribute_data

        for pf in postfixes:
            # if no conditions are specified, use postfix
            if not pf.hide_conditions.count() \
                and not pf.hide_not_conditions.count() \
                and not pf.show_conditions.count() \
                and not pf.show_not_conditions.count():
                postfix = pf
                break

            # do not use this postfix if any hide condition is fulfilled
            hide = False
            for cond_attr in pf.hide_conditions.all():
                if attribute_data.get(cond_attr.identifier):
                    hide = True
                    break

            for cond_attr in pf.hide_not_conditions.all():
                if not attribute_data.get(cond_attr.identifier):
                    hide = True
                    break

            if hide:
                continue

            # use this postfix if at least one condition is fulfilled
            for cond_attr in pf.show_conditions.all():
                if attribute_data.get(cond_attr.identifier):
                    postfix = pf
                    break

            for cond_attr in pf.show_not_conditions.all():
                if not attribute_data.get(cond_attr.identifier):
                    postfix = pf
                    break

            if postfix:
                break

        if not postfix:
            return ""

        postfix = postfix.formatting

        identifiers = re.findall(r"\{([a-zA-Z_0-9]*)\}", postfix)
        for identifier in identifiers:
            try:
                attribute = Attribute.objects.get(identifier=identifier)
                postfix = postfix.replace(
                    "{"+identifier+"}",
                    attribute.get_attribute_display(
                        attribute_data.pop(identifier, "")
                    ),
                )
            except Attribute.DoesNotExist:
                pass

        return postfix

    class Meta:
        verbose_name = _("report column")
        verbose_name_plural = _("report columns")
        ordering = ("index",)

    def __str__(self):
        return f"{self.report} ({', '.join([attr.name for attr in self.attributes.all()])})"


class ReportColumnPostfix(models.Model):
    report_column = models.ForeignKey(
        ReportColumn,
        verbose_name=_("report column"),
        on_delete=models.CASCADE,
        related_name="postfixes",
    )
    subtypes = models.ManyToManyField(
        ProjectSubtype,
        verbose_name=_("subtypes"),
        related_name="report_columns",
    )
    formatting = models.CharField(
        max_length=255,
        verbose_name=_("formatting"),
    )
    show_conditions = models.ManyToManyField(
        Attribute,
        verbose_name=_("conditions: show if..."),
        related_name="report_column_postfix_show_conditions",
        blank=True,
    )
    show_not_conditions = models.ManyToManyField(
        Attribute,
        verbose_name=_("conditions: show if not..."),
        related_name="report_column_postfix_show_not_conditions",
        blank=True,
    )
    hide_conditions = models.ManyToManyField(
        Attribute,
        verbose_name=_("conditions: hide if..."),
        related_name="report_column_postfix_hide_conditions",
        blank=True,
    )
    hide_not_conditions = models.ManyToManyField(
        Attribute,
        verbose_name=_("conditions: hide if not..."),
        related_name="report_column_postfix_hide_not_conditions",
        blank=True,
    )
    index = models.PositiveIntegerField(
        verbose_name=_("index"),
        default=0,
    )

    class Meta:
        verbose_name = _("report column postfix")
        verbose_name_plural = _("report column postfixes")
        ordering = ("index",)

    def __str__(self):
        return f"{self.formatting} ({', '.join([s.name for s in self.subtypes.all()])})"


class ReportFilter(models.Model):
    """ Filter for filtering reports """
    TYPE_EXACT = "exact"
    TYPE_MULTIPLE = "multiple"
    TYPE_RANGE = "range"
    TYPE_SET = "set"
    TYPE_NOT_SET = "not_set"

    TYPE_CHOICES = (
        (TYPE_EXACT, _("exact value")),
        (TYPE_MULTIPLE, _("multiple choice")),
        (TYPE_RANGE, _("value range")),
        (TYPE_SET, _("value is set")),
        (TYPE_NOT_SET, _("value is not set")),
    )

    INPUT_TYPE_PERSONNEL = "personnel"
    INPUT_TYPE_STRING = "string"
    INPUT_TYPE_DATE = "date"
    INPUT_TYPE_INTEGER = "integer"

    INPUT_TYPE_CHOICES = (
        (INPUT_TYPE_PERSONNEL, _("personnel")),
        (INPUT_TYPE_STRING, _("string")),
        (INPUT_TYPE_DATE, _("date")),
        (INPUT_TYPE_INTEGER, _("integer")),
    )

    name = models.CharField(
        max_length=255,
        verbose_name=_("name"),
    )
    identifier = models.CharField(
        max_length=255,
        verbose_name=_("identifier"),
    )
    type = models.CharField(
        max_length=8,
        choices=TYPE_CHOICES,
        verbose_name=_("filter type"),
    )
    input_type = models.CharField(
        max_length=9,
        choices=INPUT_TYPE_CHOICES,
        verbose_name=_("filter input type"),
        default=INPUT_TYPE_STRING,
    )
    reports = models.ManyToManyField(
        Report,
        verbose_name=_("usable with reports"),
        related_name="filters",
    )
    attributes = models.ManyToManyField(
        Attribute,
        verbose_name=_("target attributes"),
    )
    attributes_as_choices = models.BooleanField(
        verbose_name=_("use attributes as choices"),
        default=False,
    )

    def _parse_filter_input(self, value, value_type):
        if self.input_type == ReportFilter.INPUT_TYPE_DATE:
            return datetime.strptime(value, '%Y-%m-%d').date()

        return value_type(value)

    def _get_query(self, value, key, value_type):
        if value is None:
            return Q()
        elif self.type == ReportFilter.TYPE_EXACT:
            try:
                value = self._parse_filter_input(value, value_type)
            except (ValueError, TypeError):
                return Q()

            return Q(**{key: value})
        elif self.type == ReportFilter.TYPE_MULTIPLE:
            try:
                value = [
                    self._parse_filter_input(val.strip(" "), value_type)
                    for val in value
                ]
            except (ValueError, TypeError):
                return Q()

            return Q(**{f"{key}__contained_by": value})
        elif self.type == ReportFilter.TYPE_RANGE:
            try:
                value = [
                    self._parse_filter_input(val.strip(" "), value_type)
                    for val in value
                ]
            except (ValueError, TypeError):
                return Q()

            gte=value[0]
            try:
                lte=value[1]
                return Q(**{f"{key}__gte": gte, f"{key}__lte": lte})
            except IndexError:
                return Q(**{f"{key}__gte": gte})
        elif self.type == ReportFilter.TYPE_SET:
            return Q(**{f"{key}__isnull": False})
        elif self.type == ReportFilter.TYPE_NOT_SET:
            return Q(**{f"{key}__isnull": True})

    def filter_projects(self, value, queryset=Project.objects.all()):
        type_field_mapping = {
            Attribute.TYPE_INTEGER: models.IntegerField(),
            Attribute.TYPE_DECIMAL: models.FloatField(),
            Attribute.TYPE_SHORT_STRING: models.TextField(),
            Attribute.TYPE_LONG_STRING: models.TextField(),
            Attribute.TYPE_RICH_TEXT: models.TextField(),
            Attribute.TYPE_RICH_TEXT_SHORT: models.TextField(),
            Attribute.TYPE_BOOLEAN: models.BooleanField(),
            Attribute.TYPE_DATE: models.DateField(),
            Attribute.TYPE_USER: models.TextField(),
            Attribute.TYPE_PERSONNEL: models.TextField(),
            Attribute.TYPE_LINK: models.TextField(),
            Attribute.TYPE_CHOICE: models.TextField(),
        }
        value_type_mapping = {
            Attribute.TYPE_INTEGER: int,
            Attribute.TYPE_DECIMAL: float,
            Attribute.TYPE_SHORT_STRING: str,
            Attribute.TYPE_LONG_STRING: str,
            Attribute.TYPE_RICH_TEXT: str,
            Attribute.TYPE_RICH_TEXT_SHORT: str,
            Attribute.TYPE_BOOLEAN: bool,
            Attribute.TYPE_DATE: datetime.date,
            Attribute.TYPE_USER: str,
            Attribute.TYPE_PERSONNEL: str,
            Attribute.TYPE_LINK: str,
            Attribute.TYPE_CHOICE: str,
        }

        if not self.attributes_as_choices:
            choices = {}
            for attr in self.attributes.all():
                for choice in attr.value_choices.all():
                    choices[choice.identifier] = choice.value

            if self.type in [
                ReportFilter.TYPE_MULTIPLE,
                ReportFilter.TYPE_RANGE,
                ReportFilter.TYPE_SET,
                ReportFilter.TYPE_NOT_SET,
            ]:
                value = value.split(",")
                # hard-coded special case for phase and subtype
                if choices and self.identifier in ["kaavan_vaihe", "kaavaprosessi"]:
                    value = [choices.get(v) for v in value if choices.get(v)]
            elif choices:
                value = choices.get(value)

            queryset = queryset \
                .annotate(**{
                    f"search_key__{attr.identifier}": \
                        KeyTextTransform(attr.identifier, "attribute_data")
                    for attr in self.attributes.all() if not attr.fieldsets.count()
                }) \
                .annotate(**{
                    f"search_key__{attr.identifier}": \
                        Cast(
                            f"search_key__{attr.identifier}",
                            type_field_mapping[attr.value_type],
                        )
                    for attr in self.attributes.all() if not attr.fieldsets.count()
                })
            query = Q()
            User = get_user_model()

            for attr in self.attributes.all():
                # hard-coded special case for phase and subtype
                q_value = value
                if choices and self.identifier in ["kaavan_vaihe", "kaavaprosessi"]:
                    try:
                        q_value = attr.value_choices.get(identifier=value).value
                    except AttributeValueChoice.DoesNotExist:
                        pass
                elif attr.value_type == Attribute.TYPE_USER:
                    for i, qv in enumerate(q_value):
                        try:
                            q_value[i] = str(User.objects.get(ad_id=qv, hide_from_ui=False).uuid)
                        except User.DoesNotExist:
                            pass

                if not attr.fieldsets.count():
                    query |= self._get_query(
                        q_value,
                        f"attribute_data__{attr.identifier}",
                        value_type_mapping[attr.value_type],
                    )
                else:
                    if not isinstance(q_value, list):
                        q_value = [q_value]

                    for qv in q_value:
                        qv = self._parse_filter_input(
                            qv,
                            value_type_mapping[attr.value_type],
                        )
                        qv = [{attr.identifier: qv}]
                        qv_deleted = [{
                            attr.identifier: qv,
                            "_deleted": True,
                        }]
                        path = get_fieldset_path(attr)
                        for step in path[1:]:
                            qv = [{step.identifier: qv}]
                            qv_deleted = [{step.identifier: qv_deleted}]

                        query |= (
                            Q(**{
                                f"attribute_data__{path[0].identifier}__contains": qv,
                            }) & ~Q(**{
                                f"attribute_data__{path[0].identifier}__contains": qv_deleted,
                            })
                        )

            return queryset.filter(query)

        if not self.attribute_choices.count():
            query = Q()
            return_qs = queryset.none()
            for val in value.split(","):
                queryset = queryset.annotate(
                    search_key=KeyTextTransform(val, "attribute_data")
                )
                if self.type == ReportFilter.TYPE_SET:
                    return_qs = return_qs.union(
                        queryset.filter(search_key__isnull=False)
                    )
                elif self.type == ReportFilter.TYPE_NOT_SET:
                    return_qs = return_qs.union(
                        queryset.filter(search_key__isnull=True)
                    )

            return return_qs
        else:
            try:
                choices = [
                    self.attribute_choices.get(identifier=val)
                    for val in value.split(",")
                ]
            except ReportFilterAttributeChoice.DoesNotExist:
                return Project.objects.none()

            return_qs = queryset.none()
            for choice in choices:
                queryset = queryset.annotate(
                    search_key=KeyTextTransform(
                        choice.attribute.identifier, "attribute_data"
                    )
                ).annotate(
                    search_key=Cast(
                        "search_key",
                        type_field_mapping[choice.attribute.value_type],
                    )
                )
                query = self._get_query(
                    choice.value,
                    "search_key",
                    value_type_mapping[choice.attribute.value_type],
                )
                return_qs = return_qs.union(queryset.filter(query))

            return return_qs

    class Meta:
        verbose_name = _("report filter")
        verbose_name_plural = _("report filters")

    def __str__(self):
        return self.name

class ReportFilterAttributeChoice(models.Model):
    """ Additional, attribute-specific choices for a filter """
    report_filter = models.ForeignKey(
        ReportFilter,
        verbose_name=_("filter"),
        on_delete=models.CASCADE,
        related_name="attribute_choices",
    )
    attribute = models.ForeignKey(
        Attribute,
        verbose_name=_("attribute"),
        on_delete=models.CASCADE,
    )
    name = models.CharField(
        max_length=255,
        verbose_name=_("name"),
    )
    identifier = models.CharField(
        max_length=255,
        verbose_name=_("identifier"),
    )
    value = models.CharField(
        max_length=255,
        verbose_name=_("search value, values or value range"),
    )

    class Meta:
        verbose_name = _("attribute choice for report filter")
        verbose_name_plural = _("attribute choices for report filters")

    def __str__(self):
        return f"{self.report_filter}: {self.name}"
