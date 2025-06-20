import datetime
import re
import logging
import numpy as np
import requests
from requests.exceptions import Timeout
from typing import List, NamedTuple, Type

from actstream import action
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.exceptions import ObjectDoesNotExist
from django.core.serializers.json import DjangoJSONEncoder, json
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from drf_spectacular.utils import extend_schema_field, inline_serializer
from drf_spectacular.types import OpenApiTypes
from rest_framework import serializers, status
from rest_framework.exceptions import ValidationError, NotFound, ParseError
from rest_framework.response import Response
from rest_framework.serializers import Serializer

from projects.actions import verbs
from projects.helpers import (
    get_flat_attribute_data,
    set_kaavoitus_api_data_in_attribute_data,
    set_ad_data_in_attribute_data,
    set_automatic_attributes,
)
from projects.models import (
    Project,
    ProjectSubtype,
    CommonProjectPhase,
    ProjectPhase,
    ProjectPhaseLog,
    ProjectPhaseSection,
    ProjectFloorAreaSection,
    ProjectAttributeFile,
    ProjectDeadline,
    ProjectPriority,
    Attribute,
    AttributeValueChoice,
    ProjectPhaseSectionAttribute,
    ProjectComment,
    Deadline,
    DeadlineDateCalculation,
    ProjectAttributeFileFieldsetPathLocation,
    OverviewFilter,
    DocumentTemplate,
    FieldSetAttribute,
)
from projects.models.project import ProjectAttributeMultipolygonGeometry
from projects.permissions.media_file_permissions import (
    has_project_attribute_file_permissions,
)
from projects.serializers.utils import VIS_BOOL_MAP, _set_fieldset_path, get_dl_vis_bool_name
from projects.serializers.fields import AttributeDataField
from projects.serializers.document import DocumentTemplateSerializer
from projects.serializers.section import create_section_serializer
from projects.serializers.deadline import DeadlineSerializer
from sitecontent.models import ListViewAttributeColumn
from users.models import User, PRIVILEGE_LEVELS
from users.serializers import PersonnelSerializer, UserSerializer
from users.helpers import get_graph_api_access_token

log = logging.getLogger(__name__)


class SectionData(NamedTuple):
    section: ProjectPhaseSection
    serializer_class: Type[Serializer]


class ProjectDeadlineSerializer(serializers.Serializer):
    past_due = serializers.SerializerMethodField()
    out_of_sync = serializers.SerializerMethodField()
    is_under_min_distance_previous = serializers.SerializerMethodField()
    is_under_min_distance_next = serializers.SerializerMethodField()
    date = serializers.DateField()
    abbreviation = serializers.CharField(source="deadline.abbreviation")
    deadline = serializers.SerializerMethodField()
    generated = serializers.BooleanField()
    edited = serializers.DateTimeField()
    editable = serializers.BooleanField()

    @extend_schema_field(DeadlineSerializer)
    def get_deadline(self, projectdeadline):
        return DeadlineSerializer(
            projectdeadline.deadline
        ).data

    def _resolve_distance_conditions(self, distance, project):
        return distance.check_conditions(project.attribute_data)

    @extend_schema_field(OpenApiTypes.BOOL)
    def get_is_under_min_distance_next(self, projectdeadline):
        if not projectdeadline.date:
            return False

        next_deadlines = projectdeadline.deadline.distances_to_next.all()\
            .select_related("deadline", "deadline__date_type", "date_type")
        for next_distance in next_deadlines:
            # Ignore if distance conditions are not met
            if not self._resolve_distance_conditions(
                next_distance,
                projectdeadline.project,
            ):
                continue

            # Ignore if next deadline does not exist for project
            try:
                next_date = projectdeadline.project.deadlines.get(
                    deadline=next_distance.deadline
                ).date
            except ProjectDeadline.DoesNotExist:
                continue

            # Ignore if next date is not set
            if not next_date:
                continue

            # Ignore if next date is not supposed to be visible
            vis_bool = get_dl_vis_bool_name(next_distance.deadline.deadlinegroup)
            if vis_bool and not projectdeadline.project.attribute_data.get(vis_bool):
                continue

            if next_distance.date_type:
                distance_to_next = next_distance.date_type.valid_days_to(
                    projectdeadline.date, next_date
                )
            else:
                distance_to_next = (next_date - projectdeadline.date).days
            if distance_to_next < next_distance.distance_from_previous:
                return True

        return False

    @extend_schema_field(OpenApiTypes.BOOL)
    def get_is_under_min_distance_previous(self, projectdeadline):
        if not projectdeadline.date:
            return False

        prev_deadlines = projectdeadline.deadline.distances_to_previous.all()\
            .select_related("previous_deadline", "previous_deadline__date_type", "date_type")\
            .prefetch_related("previous_deadline__date_type__automatic_dates")
        for prev_distance in prev_deadlines:
            # Ignore if distance conditions are not met
            if not self._resolve_distance_conditions(
                prev_distance,
                projectdeadline.project,
            ):
                continue

            # Ignore if previous deadline does not exist for project
            try:
                prev_date = projectdeadline.project.deadlines.get(
                    deadline=prev_distance.previous_deadline
                ).date
            except ProjectDeadline.DoesNotExist:
                continue

            # Ignore if previous date is not set
            if not prev_date:
                continue

            if prev_distance.date_type:
                distance_from_prev = prev_distance.date_type.valid_days_to(
                    prev_date, projectdeadline.date
                )
            else:
                distance_from_prev = (projectdeadline.date - prev_date).days
            if distance_from_prev < prev_distance.distance_from_previous:
                return True

        return False

    @extend_schema_field(OpenApiTypes.BOOL)
    def get_past_due(self, projectdeadline):
        return len([
            dl for dl in projectdeadline.project.deadlines.filter(
                deadline__index__lte=projectdeadline.deadline.index,
                date__lt=datetime.date.today(),
            ).select_related("project", "deadline", "deadline__confirmation_attribute")
            if not dl.confirmed
        ]) > 0

    @extend_schema_field(OpenApiTypes.BOOL)
    def get_out_of_sync(self, projectdeadline):
        return projectdeadline.project.subtype != \
            projectdeadline.deadline.phase.project_subtype

    class Meta:
        model = ProjectDeadline
        fields = [
            "date",
            "abbreviation",
            "deadline_id",
            "past_due",
            "is_under_min_distance_previous",
            "is_under_min_distance_next",
            "out_of_sync",
            "distance_reference_deadline_id",
        ]


class ProjectPrioritySerializer(serializers.ModelSerializer):
    priority = serializers.IntegerField()
    name = serializers.CharField()

    class Meta:
        model = ProjectPriority
        fields = [
            "id",
            "priority",
            "name",
        ]

class ProjectOverviewSerializer(serializers.ModelSerializer):
    user = serializers.SlugRelatedField(
        slug_field="uuid",
        queryset=get_user_model().objects.all(),
    )
    user_name = serializers.SerializerMethodField()
    subtype = serializers.SerializerMethodField()
    phase = serializers.SerializerMethodField()

    def get_user_name(self, project):
        first_name = project.user.first_name
        last_name = project.user.last_name

        return " ".join([first_name, last_name])

    def get_phase(self, project):
        return ProjectPhaseSerializer(project.phase).data

    def get_subtype(self, project):
        return ProjectSubtypeSerializer(project.subtype).data

    class Meta:
        model = Project
        fields = [
            "id",
            "pino_number",
            "user",
            "user_name",
            "name",
            "subtype",
            "phase",
        ]


class OverviewFilterSerializer(serializers.ModelSerializer):
    parameter = serializers.CharField(source="identifier")
    filters_by_subtype = serializers.SerializerMethodField()
    filters_on_map = serializers.SerializerMethodField()
    filters_floor_area = serializers.SerializerMethodField()
    value_type = serializers.SerializerMethodField()
    accepts_year = serializers.SerializerMethodField()
    choices = serializers.SerializerMethodField()

    def _get_filters(self, overview_filter, filters):
        return bool(overview_filter.attributes.filter(**{filters: True}).count())

    @extend_schema_field(OpenApiTypes.BOOL)
    def get_filters_by_subtype(self, overview_filter):
        return self._get_filters(overview_filter, "filters_by_subtype")

    @extend_schema_field(OpenApiTypes.BOOL)
    def get_filters_on_map(self, overview_filter):
        return self._get_filters(overview_filter, "filters_on_map")

    @extend_schema_field(OpenApiTypes.BOOL)
    def get_filters_floor_area(self, overview_filter):
        return self._get_filters(overview_filter, "filters_floor_area")

    def get_value_type(self, overview_filter):
        # It's never validated one filter only contains one type of values;
        # trusting the admin user for now
        if overview_filter.attributes.first():
            return overview_filter.attributes.first().attribute.value_type

        return None

    @extend_schema_field(OpenApiTypes.BOOL)
    def get_accepts_year(self, overview_filter):
        for attr in overview_filter.attributes.all().prefetch_related("attribute"):
            if attr.attribute.value_type == Attribute.TYPE_DATE and \
                not attr.attribute.fieldsets.count():
                return True

        return False

    @extend_schema_field(inline_serializer(
        name='choices',
        fields={
            'label': serializers.CharField(),
            'value': serializers.CharField(),
        },
        many=True,
    ))
    def get_choices(self, overview_filter):
        choices = {}

        for attr in overview_filter.attributes.all().prefetch_related("attribute__value_choices"):
            for choice in attr.attribute.value_choices.all():
                choices[choice.identifier] = choice.value

        return [
            {"label": v, "value": k}
            for k, v in choices.items()
        ]

    class Meta:
        model = OverviewFilter
        fields = [
            "name",
            "parameter",
            "filters_by_subtype",
            "filters_on_map",
            "filters_floor_area",
            "value_type",
            "accepts_year",
            "choices",
        ]


class ProjectPhaseOverviewSerializer(serializers.ModelSerializer):
    project_count = serializers.SerializerMethodField()
    projects = serializers.SerializerMethodField()

    def get_project_count(self, phase):
        return phase.projects.filter(
            self.context.get("query", Q()),
            public=True,
        ).count()

    def get_projects(self, phase):
        return ProjectOverviewSerializer(
            phase.projects.filter(
                self.context.get("query", Q()),
                public=True,
            ).select_related("subtype", "subtype__project_type", "user"),
            many=True,
        ).data

    class Meta:
        model = ProjectPhase
        fields = [
            "name",
            "color_code",
            "color",
            "project_count",
            "projects",
        ]


class ProjectSubtypeOverviewSerializer(serializers.ModelSerializer):
    phases = serializers.SerializerMethodField()

    def get_phases(self, subtype):
        return ProjectPhaseOverviewSerializer(
            subtype.phases.all().select_related("project_subtype",
                                                "project_subtype__project_type",
                                                "common_project_phase"),
            many=True,
            context=self.context,
        ).data

    class Meta:
        model = ProjectSubtype
        fields = [
            "name",
            "phases",
        ]


class ProjectOnMapOverviewSerializer(serializers.ModelSerializer):
    geoserver_data = serializers.SerializerMethodField()
    phase_color = serializers.CharField(source="phase.color_code")
    user_name = serializers.SerializerMethodField()
    subtype = serializers.SerializerMethodField()
    phase = serializers.SerializerMethodField()

    def get_geoserver_data(self, project):  # Data is cached in projects.tasks.refresh_on_map_overview_cache periodically
        identifier = project.attribute_data.get("hankenumero")
        if not identifier:
            return None

        geoserver_data  = cache.get(f"{settings.KAAVOITUS_API_BASE_URL}/geoserver/v1/suunnittelualue/{identifier}")
        if geoserver_data and geoserver_data != "error":
            return geoserver_data

        return None

    @extend_schema_field(OpenApiTypes.STR)
    def get_user_name(self, project):
        first_name = project.user.first_name
        last_name = project.user.last_name

        return " ".join([first_name, last_name])

    # @extend_schema_field(ProjectPhaseSerializer)
    def get_phase(self, project):
        return ProjectPhaseSerializer(project.phase).data

    # @extend_schema_field(ProjectSubtypeSerializer)
    def get_subtype(self, project):
        return ProjectSubtypeSerializer(project.subtype).data

    class Meta:
        model = Project
        fields = [
            "name",
            "pk",
            "phase_color",
            "geoserver_data",
            "user",
            "user_name",
            "pino_number",
            "subtype",
            "phase",
        ]


class ProjectListSerializer(serializers.ModelSerializer):
    user = serializers.SlugRelatedField(
        read_only=False, slug_field="uuid", queryset=get_user_model().objects.all()
    )
    user_email = serializers.SerializerMethodField()
    attribute_data = AttributeDataField(allow_null=True, required=False)
    type = serializers.SerializerMethodField()
    phase_start_date = serializers.SerializerMethodField()
    deadlines = serializers.SerializerMethodField()
    priority = serializers.SerializerMethodField()

    class Meta:
        model = Project
        fields = [
            "user",
            "user_email",
            "created_at",
            "modified_at",
            "name",
            "identifier",
            "pino_number",
            "type",
            "subtype",
            "attribute_data",
            "phase",
            "id",
            "public",
            "owner_edit_override",
            "archived",
            "onhold",
            "create_principles",
            "create_draft",
            "phase_start_date",
            "deadlines",
            "priority",
        ]

    @extend_schema_field(OpenApiTypes.STR)
    def get_user_email(self, project):
        return project.user.email

    @extend_schema_field(OpenApiTypes.INT)
    def get_type(self, project):
        return project.type.pk

    @extend_schema_field(OpenApiTypes.DATE)
    def get_phase_start_date(self, project):
        try:
            return project.deadlines \
                .filter(deadline__phase=project.phase) \
                .order_by("deadline__index").first().date
        except AttributeError:
            return None

    def get_attribute_data(self, project):
        static_properties = [
            "user",
            "name",
            "public",
            "pino_number",
            "create_principles",
            "create_draft",
        ]
        return_data = {}
        attrs = self.context["listview_attribute_columns"] if self.context.__contains__("listview_attribute_columns")\
            else ListViewAttributeColumn.objects.all().select_related("attribute")
        attribute_data = getattr(project, "attribute_data", {})
        for attr in attrs:
            identifier = attr.attribute.identifier
            value = attribute_data.get(identifier)
            if attr.attribute.static_property in static_properties:
                return_data[identifier] = getattr(
                    project, attr.attribute.static_property
                )
            elif value:
                return_data[identifier] = value

        # Add deadline visibility booleans (needed in timeline preview)
        for vis_bool in VIS_BOOL_MAP.values():
            value = attribute_data.get(vis_bool, None)
            if value != None:
                return_data[vis_bool] = value

        return return_data

    @extend_schema_field(ProjectDeadlineSerializer(many=True))
    def get_deadlines(self, project):
        project_schedule_cache = self.context["project_schedule_cache"]
        return project_schedule_cache.get(project.pk, [])

    @extend_schema_field(ProjectPrioritySerializer(many=False))
    def get_priority(self, project):
        return ProjectPrioritySerializer(project.priority).data if project.priority else None


class ProjectExternalDocumentSerializer(serializers.Serializer):
    document_name = serializers.SerializerMethodField()
    link = serializers.SerializerMethodField()

    def _get_field_as_string(self, fieldset_item, attribute):
        if not attribute:
            return None

        value = fieldset_item.get(attribute.identifier)
        if attribute.value_choices.count():
            try:
                choice = attribute.value_choices.get(identifier=value)
                return choice.value
            except AttributeValueChoice.DoesNotExist:
                return value

        elif value and attribute.value_type in (
            Attribute.TYPE_RICH_TEXT, Attribute.TYPE_RICH_TEXT_SHORT
        ):
            return "".join([item["insert"] for item in value["ops"]]).strip()
        else:
            return value

    @extend_schema_field(OpenApiTypes.STR)
    def get_document_name(self, fieldset_item):
        name_attribute = self.context["document_fieldset"]. \
            document_name_attribute
        custom_name_attribute = self.context["document_fieldset"]. \
            document_custom_name_attribute

        name = self._get_field_as_string(
            fieldset_item, name_attribute
        )
        custom_name = self._get_field_as_string(
            fieldset_item, custom_name_attribute
        )

        return custom_name or name

    @extend_schema_field(OpenApiTypes.STR)
    def get_link(self, fieldset_item):
        return fieldset_item.get(
            self.context["document_fieldset"].document_link_attribute.identifier
        )


class ProjectExternalDocumentSectionSerializer(serializers.Serializer):
    section_name = serializers.SerializerMethodField()
    documents = serializers.SerializerMethodField()

    @extend_schema_field(OpenApiTypes.STR)
    def get_section_name(self, *args):
        return self.context["section"].name

    @extend_schema_field(ProjectExternalDocumentSerializer(many=True))
    def get_documents(self, project):
        section = self.context["section"]
        fields = []

        for document_fieldset in section.documentlinkfieldset_set.all():
            fieldset_data = project.attribute_data.get(
                document_fieldset.fieldset_attribute.identifier, []
            )

            for item in fieldset_data:
                if item.get(document_fieldset.document_link_attribute.identifier):
                    fields.append(ProjectExternalDocumentSerializer(
                        item, context={"document_fieldset": document_fieldset},
                    ).data)

        fields.reverse()
        return fields


class ProjectSerializer(serializers.ModelSerializer):
    user = serializers.SlugRelatedField(
        read_only=False, slug_field="uuid", queryset=get_user_model().objects.all()
    )
    user_email = serializers.SerializerMethodField()
    attribute_data = AttributeDataField(allow_null=True, required=False)
    type = serializers.SerializerMethodField()
    priority = serializers.SerializerMethodField()
    deadlines = serializers.SerializerMethodField()
    public = serializers.BooleanField(
        allow_null=True, required=False, read_only=True,
    )
    owner_edit_override = serializers.BooleanField(
        allow_null=True, required=False, read_only=True,
    )
    archived = serializers.BooleanField(
        allow_null=True, required=False, read_only=True,
    )
    onhold = serializers.BooleanField(
        allow_null=True, required=False, read_only=True,
    )
    generated_deadline_attributes = serializers.SerializerMethodField()
    deadline_attributes = serializers.SerializerMethodField()
    geoserver_data = serializers.SerializerMethodField()
    phase_documents_created = serializers.SerializerMethodField()
    phase_documents_creation_started = serializers.SerializerMethodField()

    project_type = serializers.CharField(source="projektityyppi", allow_null=True, required=False)
    project_card_document = serializers.SerializerMethodField()

    _metadata = serializers.SerializerMethodField()

    class Meta:
        model = Project
        fields = [
            "user",
            "user_email",
            "created_at",
            "modified_at",
            "phase_documents_created",
            "phase_documents_creation_started",
            "project_card_document",
            "name",
            "identifier",
            "pino_number",
            "type",
            "priority",
            "subtype",
            "attribute_data",
            "phase",
            "id",
            "public",
            "owner_edit_override",
            "archived",
            "onhold",
            "deadlines",
            "create_principles",
            "create_draft",
            "generated_deadline_attributes",
            "deadline_attributes",
            "geoserver_data",
            "project_type",
            "_metadata",
        ]
        read_only_fields = ["type", "created_at", "modified_at", "project_card_document"]

    def get_geoserver_data(self, project):  # Data is cached in projects.tasks.refresh_on_map_overview_cache periodically
        identifier = project.attribute_data.get("hankenumero")
        if not identifier:
            return None

        url = f"{settings.KAAVOITUS_API_BASE_URL}/geoserver/v1/suunnittelualue/{identifier}"
        geoserver_data  = cache.get(url)
        is_inactive = self.instance.modified_at <= timezone.now()-datetime.timedelta(days=7)

        if not geoserver_data or is_inactive:
            try:
                response = requests.get(
                    url,
                    headers={"Authorization": f"Token {settings.KAAVOITUS_API_AUTH_TOKEN}"},
                )
                if response.status_code == 200:
                    geoserver_data = response.json()
                    cache.set(url, geoserver_data, None)
                else:
                    cache.set(url, "error", 3600)
            except Timeout:
                pass

        if geoserver_data and geoserver_data != "error":
            return geoserver_data

        return None

    def _get_snapshot_date(self, project):
        query_params = getattr(self.context["request"], "GET", {})
        snapshot_param = query_params.get("snapshot")
        snapshot = None

        if snapshot_param:
            try:
                return ProjectPhaseLog.objects.filter(
                    phase__id=int(snapshot_param),
                    project=project,
                ).order_by("-created_at").first().created_at
            except AttributeError:
                raise NotFound(detail=_("Project data at selected phase start cannot be found"))
            except ValueError:
                pass

            try:
                snapshot = datetime.datetime.strptime(
                    snapshot_param,
                    "%Y-%m-%dT%H:%M:%S.%fZ%z",
                )
            except ValueError:
                try:
                    snapshot = datetime.datetime.strptime(
                        snapshot_param[:-3]+snapshot_param[-2:],
                        "%Y-%m-%dT%H:%M:%S%z",
                    )
                except ValueError:
                    raise ParseError(detail=_("Incorrect snapshot datetime format, use one of the following:\n%Y-%m-%dT%H:%M:%S.%fZ%z\n\nphase id"))

            if snapshot < project.created_at:
                raise NotFound(detail=_("Project data at selected date cannot be found"))

            return snapshot

        return None

    def get_fields(self):
        fields = super(ProjectSerializer, self).get_fields()
        request = self.context.get('request', None)

        try:
            if request.user.uuid == self.instance.user.uuid:
                fields["public"] = serializers.BooleanField(
                    allow_null=True, required=False,
                )
                fields["onhold"] = serializers.BooleanField(
                    allow_null=True, required=False,
                )
        except AttributeError:
            pass

        return fields

    def get_attribute_data(self, project):
        snapshot = self._get_snapshot_date(project)

        if snapshot:
            attribute_data = {
                k: v["new_value"]
                for k, v in self._get_updates(project, Attribute.objects.all(),
                                              cutoff=snapshot, request=self.context.get('request', None)).items()
            }
        else:
            attribute_data = getattr(project, "attribute_data", {})

        self._set_file_attributes(attribute_data, project, snapshot)

        if snapshot:
            try:
                subtype = ProjectPhaseLog.objects.filter(
                    created_at__lte=self._get_snapshot_date(project),
                    project=project
                ).order_by("-created_at").first().phase.project_subtype
            except AttributeError:
                subtype = project.phase.project_subtype
            attribute_data['kaavaprosessin_kokoluokka'] = subtype.name

        # Old versions not available for data from external APIs
        if not snapshot:
            # Because it's user-configurable, this integration is
            # extremely prone to failure. Better fail this step
            # quietly than break the whole system when misconfiguration
            # happens. (But maybe make this more granular at some point)
            try:
                set_kaavoitus_api_data_in_attribute_data(attribute_data)
            except Exception:
                pass
            set_ad_data_in_attribute_data(attribute_data)
            set_automatic_attributes(attribute_data)

        static_properties = [
            "user",
            "name",
            "public",
            "pino_number",
            "create_principles",
            "create_draft",
        ]

        if not snapshot:
            # Prevent making database calls within for-loop by getting attributes from database here
            attributes = Attribute.objects.filter(static_property__in=static_properties)
            for static_property in static_properties:
                attribute = next(filter(lambda attr: attr.static_property == static_property, attributes), None)
                if attribute:
                    value = getattr(project, static_property)

                    if attribute.value_type == Attribute.TYPE_USER:
                        value = value.uuid

                    attribute_data[attribute.identifier] = value

        return attribute_data

    @extend_schema_field(OpenApiTypes.STR)
    def get_user_email(self, project):
        return project.user.email

    @extend_schema_field(OpenApiTypes.INT)
    def get_type(self, project):
        return project.type.pk

    @extend_schema_field(ProjectPrioritySerializer(many=False))
    def get_priority(self, project):
        return ProjectPrioritySerializer(project.priority).data if project.priority else None

    @extend_schema_field(ProjectDeadlineSerializer(many=True))
    def get_deadlines(self, project):
        project_schedule_cache = cache.get("serialized_project_schedules", {})
        deadlines = ProjectDeadline.objects.filter(project=project, deadline__subtype=project.subtype)\
            .select_related("deadline", "project")\
            .prefetch_related("project__subtype", "project__deadlines", "project__deadlines__deadline",
                              "project__deadlines__project", "deadline__distances_to_previous",
                              "deadline__distances_to_next", "deadline__attribute", "deadline__phase",
                              "deadline__subtype", "deadline__date_type", "deadline__phase__project_subtype")
        if not project.create_principles:
            deadlines = deadlines.filter(~Q(deadline__phase__common_project_phase__name="Periaatteet"))
        if not project.create_draft:
            deadlines = deadlines.filter(~Q(deadline__phase__common_project_phase__name="Luonnos"))

        schedule = project_schedule_cache.get(project.pk)
        if self.context.get('should_update_deadlines') or not schedule:
            schedule = ProjectDeadlineSerializer(
                deadlines,
                many=True,
                allow_null=True,
                required=False,
            ).data

        project_schedule_cache[project.pk] = schedule
        cache.set("serialized_project_schedules", project_schedule_cache, None)
        return schedule

    @extend_schema_field(serializers.ListSerializer(child=serializers.CharField()))
    def get_generated_deadline_attributes(self, project):
        return [
            dl.deadline.attribute.identifier
            for dl in project.deadlines.filter(generated=True).select_related("deadline__attribute")
            if dl.deadline.attribute
        ]

    @extend_schema_field(serializers.ListSerializer(child=serializers.CharField()))
    def get_deadline_attributes(self, project):
        return [
            dl.deadline.attribute.identifier
            for dl in project.deadlines.filter().select_related("deadline__attribute")
            if dl.deadline.attribute
        ]

    @extend_schema_field(OpenApiTypes.BOOL)
    def get_phase_documents_created(self, project):
        return project.phase_documents_created

    def get_project_card_document(self, project):
        template = DocumentTemplate.objects.filter(project_card_default_template=True).first()
        if not template:
            return None

        return DocumentTemplateSerializer(template, many=False, context={
            "project": project,
            "request": self.context.get("request")},
        ).data

    @extend_schema_field(OpenApiTypes.BOOL)
    def get_phase_documents_creation_started(self, project):
        return project.phase_documents_creation_started

    def _set_file_attributes(self, attribute_data, project, snapshot):
        request = self.context["request"]
        if snapshot:
            attribute_files = ProjectAttributeFile.objects \
                .filter(project=project, created_at__lte=snapshot) \
                .exclude(archived_at__lte=snapshot) \
                .order_by(
                    "fieldset_path_str",
                    "attribute__pk",
                    "project__pk",
                    "-created_at",
                ) \
                .distinct("fieldset_path_str", "attribute__pk", "project__pk")
        else:
            attribute_files = ProjectAttributeFile.objects \
                .filter(project=project, archived_at=None) \
                .prefetch_related("attribute", "fieldset_path_locations") \
                .order_by(
                    "fieldset_path_str",
                    "attribute__pk",
                    "project__pk",
                    "-created_at",
                ) \
                .distinct("fieldset_path_str", "attribute__pk", "project__pk")

        # Add file attributes to the attribute data
        # File values are represented as absolute URLs
        file_attributes = {}
        for attribute_file in attribute_files:
            if has_project_attribute_file_permissions(attribute_file, request):
                if not attribute_file.fieldset_path:
                    file_attributes[attribute_file.attribute.identifier] = {
                        "link": request.build_absolute_uri(attribute_file.file.url),
                        "description": attribute_file.description,
                    }
                else:
                    file_fs_index = attribute_file.fieldset_path[0]["index"]
                    file_fs_parent_identifier = \
                        attribute_file.fieldset_path[0]["parent"].identifier
                    indices_set = len(file_attributes.get(
                        file_fs_parent_identifier, [],
                    ))
                    # include in-between fieldset children with no files
                    # that otherwise get removed in this step
                    if not file_attributes.get(file_fs_parent_identifier):
                        file_attributes[file_fs_parent_identifier] = []

                    for i in range(indices_set, file_fs_index):
                        try:
                            file_attributes[file_fs_parent_identifier].append(
                                attribute_data.get(
                                    file_fs_parent_identifier, [],
                                )[i]
                            )
                        except IndexError:
                            file_attributes[file_fs_parent_identifier].append({})

                    try:
                        fieldset_content = self.instance.attribute_data.get(
                            attribute_file.fieldset_path[0]["parent"].identifier, []
                        )[attribute_file.fieldset_path[0]["index"]]
                    except (KeyError, IndexError, TypeError):
                        fieldset_content = {}

                    _set_fieldset_path(
                        fieldset_content,
                        attribute_file.fieldset_path,
                        file_attributes,
                        0,
                        attribute_file.attribute.identifier,
                        {
                            "link": request.build_absolute_uri(attribute_file.file.url),
                            "description": attribute_file.description,
                        }
                    )

                    current_fs_len = len(file_attributes.get(
                        file_fs_parent_identifier
                    ) or [])
                    total_fs_len = len(attribute_data.get(
                        file_fs_parent_identifier
                    ) or [])

                    if current_fs_len < total_fs_len:
                        file_attributes[file_fs_parent_identifier] += \
                            attribute_data[file_fs_parent_identifier][
                                current_fs_len:total_fs_len
                            ]

        attribute_data.update(file_attributes)

    def get__metadata(self, project):
        list_view = self.context.get("action", None) == "list"
        attributes = Attribute.objects.all().select_related("key_attribute").prefetch_related("fieldsets", "fieldset_attributes"
        )  # perform further filtering of attributes within methods
        metadata = {
            "users": self._get_users(project, attributes, list_view=list_view),
            "personnel": self._get_personnel(project, attributes, list_view=list_view),
        }
        query_params = getattr(self.context["request"], "GET", {})
        snapshot_param = query_params.get("snapshot")
        if not list_view and not snapshot_param:
            metadata["updates"] = self._get_updates(
                project,
                attributes,
                cutoff=None,
                request=self.context.get('request', None)
            )

        created = project.target_actions.filter(verb=verbs.CREATED_PROJECT) \
            .prefetch_related("actor").first()

        try:
            metadata["created"] = {
                "user": created.actor.uuid,
                "user_name": created.actor.get_display_name(),
                "timestamp": created.timestamp,
            }
        # Some older projects may be missing created log info
        except AttributeError:
            metadata["created"] = {
                "user": None,
                "user_name": None,
                "timestamp": project.created_at,
            }

        return metadata

    @staticmethod
    def _get_users(project, attributes, list_view=False):
        users = [project.user]

        if not list_view:
            user_attribute_ids = set()
            for attribute in filter(
                    lambda a:
                    a.value_type in [Attribute.TYPE_USER, Attribute.TYPE_FIELDSET, Attribute.TYPE_INFO_FIELDSET],
                    attributes
            ):
                if attribute.value_type in [Attribute.TYPE_FIELDSET, Attribute.TYPE_INFO_FIELDSET]:
                    fieldset_user_identifiers = attribute.fieldset_attributes.filter(value_type=Attribute.TYPE_USER)\
                        .prefetch_related("identifier").values_list("identifier", flat=True)
                    if attribute.identifier in project.attribute_data:
                        user_attribute_ids |= ProjectSerializer._get_fieldset_attribute_values(
                            project, attribute, fieldset_user_identifiers
                        )
                else:
                    user_id = project.attribute_data.get(attribute.identifier, None)
                    if user_id:
                        user_attribute_ids.add(user_id)

            # Do not include the user of the project
            if str(project.user.uuid) in user_attribute_ids:
                user_attribute_ids.remove(str(project.user.uuid))

            users += list(User.objects.filter(uuid__in=user_attribute_ids).prefetch_related(
                "groups", "additional_groups", "additional_groups__permissions"
            ))

        return UserSerializer(users, many=True).data

    @staticmethod
    def _get_personnel(project, attributes, list_view=False):
        if list_view:
            return []

        flat_data = get_flat_attribute_data(project.attribute_data, {})

        ids = []

        for attr in filter(lambda a: a.value_type == Attribute.TYPE_PERSONNEL, attributes):
            value = flat_data.get(attr.identifier)

            if not value:
                continue
            elif type(value) is list:
                ids += set(value)
            else:
                ids.append(value)

        return_values = []

        for id in set(ids):
            url = f"{settings.GRAPH_API_BASE_URL}/v1.0/users/{id}"
            personnel_data = cache.get(url)
            if not personnel_data:
                token = get_graph_api_access_token()
                if not token:
                    return Response(
                        "Cannot get access token",
                        status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    )
                response = requests.get(
                    url, headers={"Authorization": f"Bearer {token}"}
                )

                if not response:
                    continue

                personnel_data = response.json()
                cache.set(url, personnel_data, 28800)

            data = PersonnelSerializer(personnel_data).data
            return_values.append({"id": id, "name": data["name"]})

        return return_values

    @staticmethod
    def _get_fieldset_attribute_values(
        project, fieldset_attribute, fieldset_identifiers
    ):
        values = set()
        for entry in project.attribute_data[fieldset_attribute.identifier]:
            for identifier in fieldset_identifiers:
                value = entry.get(identifier, None)
                if value:
                    values.add(value)

        return values

    @staticmethod
    def _get_updates(project, attributes, cutoff=None, request=None):
        def get_editable(attribute):
            from users.models import privilege_as_int

            if not request or not request.user:
                return False

            user = request.user
            owner = request.query_params.get("owner", False)
            is_owner = \
                owner in ["1", "true", "True"] or \
                project and project.user == user

            privilege = privilege_as_int(user.privilege)

            # owner can edit owner-editable fields regardless of their role
            if is_owner and attribute.owner_editable:
                return True
            # check privilege for others
            elif attribute.edit_privilege and \
                privilege >= privilege_as_int(attribute.edit_privilege):
                return True
            else:
                return False

        def get_attribute_schema(attribute_list, schema):
            if not attribute_list or type(attribute_list) != list:
                return

            for attr in attribute_list:
                if type(attr) == str:
                    attribute = next(filter(lambda a: a.identifier == attr, attributes), None)
                    if attribute:
                        schema.update({
                            attribute.identifier: {
                                'label': attribute.name,
                                'type': attribute.value_type,
                                'autofill_readonly': bool(attribute.autofill_readonly),
                                'editable': get_editable(attribute),
                            },
                        })
                elif type(attr) == dict:
                    for identifier, value in attr.items():
                        attribute = next(filter(lambda a: a.identifier == identifier, attributes), None)
                        if attribute:
                            schema.update({
                                attribute.identifier: {
                                    'label': attribute.name,
                                    'type': attribute.value_type,
                                    'autofill_readonly': bool(attribute.autofill_readonly),
                                    'editable': get_editable(attribute),
                                },
                            })
                        if type(value) == list:
                            get_attribute_schema(value, schema)
                else:
                    log.warn('Unsupported schema format: %r' % attr)

        def get_schema(attribute_identifier, data, labels):
            schema = {}

            attribute = next(filter(lambda a: a.identifier == attribute_identifier, attributes), None)
            # log.info('%s: %s' % (attribute_identifier, attribute))
            if attribute:
                schema.update({
                    attribute_identifier: {
                        'label': attribute.name,
                        'type': attribute.value_type,
                        'autofill_readonly': bool(attribute.autofill_readonly),
                        'editable': get_editable(attribute),
                    },
                })

            get_attribute_schema(data.get("old_value", None), schema)
            get_attribute_schema(data.get("new_value", None), schema)

            if labels:
                for key, value in labels.items():
                    schema.update({
                        key: {
                            'label': value,
                            'type': Attribute.TYPE_LONG_STRING,
                        },
                    })

            return schema

        # Get the latest attribute updates for distinct attributes
        if cutoff:
            actions = (
                project.target_actions.filter(
                    verb=verbs.UPDATED_ATTRIBUTE,
                    timestamp__lte=cutoff,
                )
                .order_by(
                    "data__attribute_identifier",
                    "action_object_content_type",
                    "action_object_object_id",
                    "-timestamp",
                )
                .distinct(
                    "data__attribute_identifier",
                    "action_object_content_type",
                    "action_object_object_id",
                )

                .prefetch_related("actor")
            )
        else:
            actions = (
                project.target_actions.filter(verb=verbs.UPDATED_ATTRIBUTE)
                .order_by(
                    "data__attribute_identifier",
                    "action_object_content_type",
                    "action_object_object_id",
                    "-timestamp",
                )
                .distinct(
                    "data__attribute_identifier",
                    "action_object_content_type",
                    "action_object_object_id",
                )

                .prefetch_related("actor")
            )

        updates = {}
        for _action in actions:
            attribute_identifier = (
                _action.data.get("attribute_identifier", None)
                or _action.action_object.identifier
            )
            # Filter out fieldset[x].attribute entries
            if not '].' in attribute_identifier:
                updates[attribute_identifier] = {
                    "user": _action.actor.uuid,
                    "user_name": _action.actor.get_display_name(),
                    "timestamp": _action.timestamp,
                    "new_value": _action.data.get("new_value", None),
                    "old_value": _action.data.get("old_value", None),
                    "schema": get_schema(
                        attribute_identifier,
                        _action.data,
                        _action.data.get("labels", {}),
                    ),
                }

        return updates

    def should_validate_attributes(self):
        # Always validate if not explicitly turned off
        if "validate_attribute_data" in self.context["request"].data:
            validate_field_data = self.context["request"].data.get(
                "validate_attribute_data", False
            )
        else:
            validate_field_data = True

        return serializers.BooleanField().to_internal_value(validate_field_data)

    def _get_keys(self):
        try:
            return self.context["request"].data.get('attribute_data').keys()
        except AttributeError:
            return re.findall(
                r'"([a-zA-Z0-9_]*)":',
                self.context["request"].data.get('attribute_data'),
            )

    def generate_sections_data(
        self,
        phase: ProjectPhase,
        preview,
        validation: bool = True,
    ) -> List[SectionData]:
        sections = []
        sections_to_serialize = phase.sections \
            .filter(attributes__identifier__in=self._get_keys()) \
            .order_by("index")
        for section in sections_to_serialize:
            serializer_class = create_section_serializer(
                section,
                context=self.context,
                project=self.instance,
                validation=validation,
                preview=preview,
            )
            section_data = SectionData(section, serializer_class)
            sections.append(section_data)
        return sections

    def generate_floor_area_sections_data(
        self, floor_area_sections, preview, validation: bool = True
    ) -> List[SectionData]:
        sections = []
        sections_to_serialize = floor_area_sections \
            .filter(attributes__identifier__in=self._get_keys()) \
            .order_by("index")
        for section in sections_to_serialize:
            serializer_class = create_section_serializer(
                section,
                context=self.context,
                project=self.instance,
                validation=validation,
                preview=preview,
            )
            section_data = SectionData(section, serializer_class)
            sections.append(section_data)

        return sections

    def generate_schedule_sections_data(self, phase, preview, validation=True):
        sections = []
        deadline_sections = phase.deadline_sections.filter(
            attributes__identifier__in=self._get_keys()
        )
        for section in deadline_sections:
            if section.phase.name == "Luonnos" and not self.instance.create_draft or (
            section.phase.name == "Periaatteet" and not self.instance.create_principles):
                continue
            serializer_class = create_section_serializer(
                section,
                context=self.context,
                project=self.instance,
                validation=validation,
                preview=preview,
            )
            section_data = SectionData(section, serializer_class)
            sections.append(section_data)
        return sections

    def validate(self, attrs):
        archived = attrs.get('archived')
        was_archived = self.instance and self.instance.archived

        if archived is not False:
            if was_archived:
                raise ValidationError(
                    {"phase": _("Archived projects cannot be edited")}
                )
            elif archived is True:
                attrs["archived_at"] = timezone.now()

        if attrs.get("subtype") and self.instance is not None:
            attrs["phase"] = self._validate_phase(attrs)

        public = self._validate_public(attrs)

        if public:
            attrs["public"] = public

        attrs["owner_edit_override"] = self._validate_owner_edit_override(attrs)

        subtype = attrs.get("subtype")
        if not subtype and self.instance:
            subtype = self.instance.subtype

        if attrs.get("create_principles") or attrs.get("create_draft"):
            if subtype and subtype.name != "XL":
                raise ValidationError({"subtype": _("Principles and drafts can only be created for XL projects.")})
        elif attrs.get("create_principles") == False and \
            attrs.get("create_draft") == False:
            if subtype and subtype.name == "XL":
                raise ValidationError({"subtype": _("Principles and/or draft needs to be created for XL projects.")})
        attrs["attribute_data"] = self._validate_attribute_data(
            attrs.get("attribute_data", None),
            attrs,
            self.instance.user if self.instance else None,
            self.instance.owner_edit_override if self.instance else None,
        )
        return attrs

    def _get_should_update_deadlines(self, subtype_changed, instance, attribute_data):
        if subtype_changed:
            return True
        elif instance:
            attr_identifiers = list(attribute_data.keys())
            should_update_deadlines = bool(
                instance.deadlines.prefetch_related("deadline").filter(
                    deadline__attribute__identifier__in=attr_identifiers
                ).exists()
            )

            if not should_update_deadlines:
                should_update_deadlines = bool(
                    Deadline.objects.filter(
                        subtype=instance.subtype,
                        condition_attributes__identifier__in=attr_identifiers,
                    ).exists()
                )

            if not should_update_deadlines:
                should_update_deadlines = bool(Deadline.objects.filter(
                    subtype=instance.subtype,
                    attribute__identifier__in=attr_identifiers
                ).exists())

            if not should_update_deadlines:
                should_update_deadlines= bool(DeadlineDateCalculation.objects.filter(
                    deadline__project_deadlines__project=instance
                ).filter(
                    Q(conditions__identifier__in=attr_identifiers) | \
                    Q(not_conditions__identifier__in=attr_identifiers) | \
                    Q(datecalculation__base_date_attribute__identifier__in=attr_identifiers) | \
                    Q(datecalculation__attributes__attribute__identifier__in=attr_identifiers)
                ).exists())

        return should_update_deadlines

    def _validate_attribute_data(self, attribute_data, validate_attributes, user, owner_edit_override):
        static_property_attributes = {}
        if self.instance:
            static_properties = [
                "user",
                "name",
                "public",
                "pino_number",
                "create_principles",
                "create_draft",
            ]
            for static_property in static_properties:
                try:
                    try:
                        attr = validate_attributes[static_property]
                    except KeyError:
                        continue

                    static_property_attributes[
                        Attribute.objects.get(static_property=static_property).identifier
                    ] = attr
                except Attribute.DoesNotExist:
                    continue

        if not attribute_data:
            return static_property_attributes

        tmp_attribute_data = {}
        attribute_objects = { attribute.identifier: attribute for attribute in Attribute.objects.filter(
            identifier__in=attribute_data.keys())}
        for attribute_identifier, value in attribute_data.items():
            try:
                attribute = attribute_objects.get(attribute_identifier)
                if not attribute:
                    continue
                if attribute.multiple_choice and attribute.value_type == Attribute.TYPE_CHOICE:
                    if value is None:
                        tmp_attribute_data[attribute_identifier] = []
                elif attribute.value_type == Attribute.TYPE_FIELDSET and value:
                    for index, entry in enumerate(value):
                        if entry.get("_deleted", False) is not True:
                            continue
                        old_value = self.instance.attribute_data.get(attribute_identifier, None)
                        if not old_value or not old_value[index] or old_value[index]["_deleted"]:
                            continue
                        fieldset_attributes = FieldSetAttribute.objects.filter(
                            attribute_source=attribute,
                            attribute_target__value_type=Attribute.TYPE_IMAGE
                        )
                        for f_attr in fieldset_attributes:
                            fieldset_path_str = f'{attribute_identifier}[{index}].{f_attr.attribute_target.identifier}'
                            ProjectAttributeFile.objects.filter(
                                project=self.instance,
                                attribute=f_attr.attribute_target,
                                fieldset_path_str=fieldset_path_str
                            ).update(archived_at=timezone.now())

                if value is None:
                    try:
                        deadline = Deadline.objects.get(attribute=attribute, subtype=self.instance.subtype)
                        ProjectDeadline.objects.get(deadline=deadline, project=self.instance).delete()
                    except Exception:
                        pass



            except Attribute.DoesNotExist:
                pass  # Attribute not found by attribute_identifier
        attribute_data.update(tmp_attribute_data)

        # Get serializers for all sections in all phases
        sections_data = []
        current_phase = getattr(self.instance, "phase", None)
        subtype = getattr(self.instance, "subtype", None) or \
            validate_attributes.get("subtype")
            # TODO: check if this subtype should be an attribute of phase object instead
            #validate_attributes.get("phase").project_subtype
        should_validate = self.should_validate_attributes()
        min_phase_index = current_phase.index if current_phase else 1

        try:
            is_owner = self.context["request"].user == self.user
            if owner_edit_override and is_owner:
                min_phase_index = 1
        except AttributeError:
            pass

        should_update_deadlines = self._get_should_update_deadlines(
            False, self.instance, attribute_data,
        )
        preview = None
        if self.instance and should_update_deadlines:
            preview = self.instance.get_preview_deadlines(
                attribute_data,
                subtype,
                self.context["confirmed_fields"],
            )
        # Phase index 1 is always editable
        # Otherwise only current phase and upcoming phases are editable
        for phase in ProjectPhase.objects.filter(project_subtype=subtype) \
            .exclude(index__range=[2, min_phase_index-1]):
            sections_data += self.generate_sections_data(
                phase=phase,
                preview=preview,
                validation=should_validate,
            ) or []
            sections_data += self.generate_schedule_sections_data(
                phase=phase,
                validation=should_validate,
                preview=preview,
            ) or []
        sections_data += self.generate_floor_area_sections_data(
            floor_area_sections=ProjectFloorAreaSection.objects.filter(project_subtype=subtype),
            validation=should_validate,
            preview=preview,
        ) or []
        # To be able to validate the entire structure, we set the initial attributes
        # to the same as the already saved instance attributes.
        valid_attributes = {}
        # if self.should_validate_attributes() and self.instance.attribute_data:
        #     # Make a deep copy of the attribute data if we are validating.
        #     # Can't assign straight since the values would be a reference
        #     # to the instance value. This will cause issues if attributes are
        #     # later removed while looping in the Project.update_attribute_data() method,
        #     # as it would mutate the dict while looping over it.
        #     valid_attributes = copy.deepcopy(self.instance.attribute_data)

        errors = {}
        for section_data in sections_data:
            # Get section serializer and validate input data against it
            serializer = section_data.serializer_class(data=attribute_data)
            if not serializer.is_valid(raise_exception=False):
                errors.update(serializer.errors)
            valid_attributes.update(serializer.validated_data)
        # If we should validate attribute data, then raise errors if they exist
        if self.should_validate_attributes() and errors:
            raise ValidationError(errors)


        def is_confirmed(dl):
            try:
                identifier = dl.deadline.confirmation_attribute.identifier
            except AttributeError:
                return None
            
            new_confirm_val = attribute_data.get(identifier, None)
            old_confirm_val = self.instance.attribute_data.get(identifier, None)

            # Newly confirmed values can be edited (not counted as confirmed)
            if not old_confirm_val:
                return False
            # Previously confirmed values cannot be edited, unless they are newly set to false.
            if new_confirm_val == None:
                return True
            return new_confirm_val

        # Confirmed deadlines can't be edited
        confirmed_deadlines = [
            dl.deadline.attribute.identifier for dl
            in self.instance.deadlines.all().select_related("deadline", "project", "deadline__confirmation_attribute")
            if not dl.editable or (is_confirmed(dl) and dl.deadline.attribute)
        ] if self.instance else []

        if confirmed_deadlines:
            valid_attributes = {
                k: v for k, v in valid_attributes.items()
                if k not in confirmed_deadlines
            }
        # mostly invalid identifiers, but could be fieldset file fields
        unusual_identifiers = list(np.setdiff1d(
            list(attribute_data.keys()),
            list(valid_attributes.keys()),
        ))

        invalid_identifiers = []
        files_to_archive = []
        for identifier in unusual_identifiers:
            try:
                attribute_file = ProjectAttributeFile.objects.get(
                    archived_at=None,
                    fieldset_path_str=identifier,
                    project=self.instance,
                )
                files_to_archive.append((identifier, attribute_file))

            except (ProjectAttributeFile.DoesNotExist, Attribute.DoesNotExist) as e:
                invalid_identifiers.append(identifier)


        if len(invalid_identifiers):
            invalids = [f"{key}: {_('Cannot edit field.')}" for key in invalid_identifiers]
            log.warning(", ".join(invalids))


        for identifier, attribute_file in files_to_archive:
            entry = action.send(
                user,
                verb=verbs.UPDATED_ATTRIBUTE,
                action_object=attribute_file.attribute,
                target=self.instance,
                attribute_identifier=identifier,
                new_value=None,
                old_value=attribute_file.description,
            )
            timestamp = entry[0][1].timestamp

            attribute_file.archived_at = timestamp
            attribute_file.save()

        if self.instance:
            updated_dls = ProjectDeadline.objects.filter(
                project=self.instance,
                deadline__attribute__identifier__in=valid_attributes.keys()
            )
            for dl in updated_dls:
                dl.generated = False
            ProjectDeadline.objects.bulk_update(updated_dls, ["generated"])

        return {**static_property_attributes, **valid_attributes}

    def _validate_public(self, attrs):
        public = attrs.get("public")

        # Do not validate if this is a new project
        if not self.instance:
            return public if public is not None else True

        # A project is always public if it has exited the starting phase
        try:
            phase_index = attrs["phase"].index
        except KeyError:
            phase_index = self.instance.phase.index

        if not self.instance.public and (phase_index > 1):
            return True

        if public is None:
            return self.instance.public

        return public

    def _validate_owner_edit_override(self, attrs):
        owner_edit_override = attrs.get("owner_edit_override", False)
        is_admin = self.context["request"].user.has_privilege("admin")

        if self.instance and is_admin:
            if owner_edit_override is None:
                return self.instance.owner_edit_override
            else:
                return owner_edit_override
        elif self.instance:
            return self.instance.owner_edit_override
        else:
            return False

    def validate_phase(self, phase, subtype_id=None):
        if not subtype_id:
            try:
                subtype_id = int(self.get_initial()["subtype"])
            except KeyError:
                subtype_id = self.instance.subtype.pk

        def _get_relative_phase(phase, offset):
            return phase.project_subtype.phases.get(index=phase.index + offset)

        offset = None

        # TODO hard-coded for now
        if phase.name == "Suunnitteluperiaatteet":
            if phase.project_subtype.pk == subtype_id:
                if not self.instance.create_principles:
                    offset = 1
            else:
                offset = -1

        if phase.name == "Luonnos":
            if phase.project_subtype.pk == subtype_id:
                if not self.instance.create_draft:
                    offset = 1
            else:
                offset = -2

        if offset:
            phase = _get_relative_phase(phase, offset)

        if phase.project_subtype.pk == subtype_id:
            return phase
        # Try to find a corresponding phase for current subtype
        else:
            try:
                return ProjectPhase.objects.get(common_project_phase__name=phase.name, project_subtype__pk=subtype_id)
            except ProjectPhase.DoesNotExist:
                pass
            try:
                return ProjectPhase.objects.get(index=phase.index, project_subtype__pk=subtype_id)
            except ProjectPhase.DoesNotExist:
                raise ValidationError(
                    {"phase": _("Invalid phase for project subtype, no substitute found")}
                )

    def _validate_phase(self, attrs):
        try:
            return attrs["phase"]
        except KeyError:
            return self.validate_phase(
                ProjectPhase.objects.get(pk=self.instance.phase.pk),
                subtype_id=attrs["subtype"].id
            )

    def validate_user(self, user):
        if not user.has_privilege('create'):
            raise ValidationError(
                {"user": _("Selected user does not have the required role")}
            )

        return user

    def create(self, validated_data: dict) -> Project:
        validated_data["phase"] = ProjectPhase.objects.filter(
            project_subtype=validated_data["subtype"]
        ).first()

        with transaction.atomic():
            self.context['should_update_deadlines'] = True
            attribute_data = validated_data.pop("attribute_data", {})
            self.set_initial_data(attribute_data, validated_data)

            project: Project = super().create(validated_data)
            user = self.context["request"].user
            action.send(
                user,
                verb=verbs.CREATED_PROJECT,
                action_object=project,
                target=project,
            )
            self.log_updates_attribute_data(attribute_data, project)

            # Update attribute data after saving the initial creation has
            # taken place so that there is no need to rewrite the entire
            # create function, even if the `update_attribute_data())` method
            # only sets values and does not make a `save()` call
            if attribute_data:
                project.update_attribute_data(attribute_data)
                project.save()

            user=self.context["request"].user
            project.update_deadlines(user=user, initial=True, preview_attributes=project.attribute_data)
            for dl in project.deadlines.all():
                self.create_deadline_updates_log(
                    dl.deadline, project, user, None, dl.date
                )

        return project

    def set_initial_data(self, attribute_data, validated_data):
        kokoluokka = validated_data["phase"].project_subtype.name

        if kokoluokka == "XL" and validated_data.get("create_draft", None) is True:
            attribute_data["kaavaluonnos_lautakuntaan_1"] = True
            attribute_data["jarjestetaan_luonnos_esillaolo_1"] = True
        if kokoluokka == "XL" and validated_data.get("create_principles", None) is True:
            attribute_data["periaatteet_lautakuntaan_1"] = True
            attribute_data["jarjestetaan_periaatteet_esillaolo_1"] = True
        attribute_data["kaavaprosessin_kokoluokka_readonly"] = kokoluokka
        try:
            attribute_data["projektityyppi"] = AttributeValueChoice.objects.get(value="Asemakaava")
        except:
            pass

    def update(self, instance: Project, validated_data: dict) -> Project:
        attribute_data = validated_data.pop("attribute_data", {})
        confirmed_fields = self.context["confirmed_fields"]
        subtype = validated_data.get("subtype")
        subtype_changed = subtype is not None and subtype != instance.subtype
        phase = validated_data.get("phase")
        phase_changed = phase is not None and phase != instance.phase
        draft_principles_changed = 'create_draft' in validated_data or 'create_principles' in validated_data
        should_generate_deadlines = getattr(
            self.context["request"], "GET", {}
        ).get("generate_schedule") in ["1", "true", "True"]
        user=self.context["request"].user

        if phase_changed:
            ProjectPhaseLog.objects.create(
                project=instance,
                phase=phase,
                user=user,
            )

        if subtype_changed or draft_principles_changed:
            #  Clear project from cache
            for owner in ['True', 'False']:
                for privilege, role in PRIVILEGE_LEVELS:
                    cache.delete(f'phase_schema:{privilege}:{owner}:{instance.pk if instance else None}')
                    if draft_principles_changed:
                        cache.delete(f'deadline_sections:{privilege}:{owner}:{instance.pk if instance else None}')

        should_update_deadlines = self._get_should_update_deadlines(
            subtype_changed or draft_principles_changed, instance, attribute_data,
        )
        self.context['should_update_deadlines'] = \
            should_update_deadlines or should_generate_deadlines

        with transaction.atomic():
            self.log_updates_attribute_data(attribute_data)
            try:
                attribute_data["projektityyppi"] = AttributeValueChoice.objects.get(value="Asemakaava")
            except:
                pass

            self.update_initial_data(validated_data)
            if attribute_data:
                instance.update_attribute_data(attribute_data, confirmed_fields=confirmed_fields)

            project = super(ProjectSerializer, self).update(instance, validated_data)

            old_deadlines = None
            if should_update_deadlines or should_generate_deadlines:
                old_deadlines = project.deadlines.all().select_related("deadline")

            if should_generate_deadlines:
                cleared_attributes = {
                    project_dl.deadline.attribute.identifier: None
                    for project_dl in project.deadlines.all().select_related("deadline", "deadline__attribute")
                    if project_dl.deadline.attribute
                }
                project.update_attribute_data(cleared_attributes)
                self.log_updates_attribute_data(cleared_attributes)
                project.deadlines.all().delete()
                project.update_deadlines(user=user, preview_attributes=attribute_data, confirmed_fields=confirmed_fields)
            elif should_update_deadlines:
                project.update_deadlines(user=user, preview_attributes=attribute_data, confirmed_fields=confirmed_fields)
                project.deadlines.filter(deadline__attribute__identifier__in=attribute_data.keys())\
                    .update(edited=timezone.now())

            project.save()

            if old_deadlines:
                project_deadlines = project.deadlines.all().select_related("deadline")
                updated_deadlines = old_deadlines.union(project_deadlines)
                for dl in updated_deadlines:
                    project_deadline = next(filter(lambda _dl: _dl.deadline == dl.deadline, project_deadlines), None)
                    new_date = project_deadline.date if project_deadline else None

                    old_deadline = next(filter(lambda _dl: _dl.deadline == dl.deadline, old_deadlines), None)
                    old_date = old_deadline.date if old_deadline else None

                    self.create_deadline_updates_log(
                        dl.deadline, project, user, old_date, new_date
                    )
            return project

    def update_initial_data(self, validated_data):
        attribute_data = self.instance.attribute_data

        try:
            kokoluokka = validated_data["phase"].project_subtype.name
            create_draft = validated_data.get("create_draft", None)
            create_principles = validated_data.get("create_principles", None)

            if create_draft is not None:
                if kokoluokka == "XL" and create_draft == True:
                    if attribute_data.get("kaavaluonnos_lautakuntaan_1", None) is None:
                        attribute_data["kaavaluonnos_lautakuntaan_1"] = True
                    if attribute_data.get("jarjestetaan_luonnos_esillaolo_1", None) is None:
                        attribute_data["jarjestetaan_luonnos_esillaolo_1"] = True
                else:
                    attribute_data.pop("kaavaluonnos_lautakuntaan_1", None)
                    attribute_data.pop("jarjestetaan_luonnos_esillaolo_1", None)

            if create_principles is not None:
                if kokoluokka == "XL" and create_principles == True:
                    if attribute_data.get("periaatteet_lautakuntaan_1", None) is None:
                        attribute_data["periaatteet_lautakuntaan_1"] = True
                    if attribute_data.get("jarjestetaan_periaatteet_esillaolo_1", None) is None:
                        attribute_data["jarjestetaan_periaatteet_esillaolo_1"] = True
                else:
                    attribute_data.pop("periaatteet_lautakuntaan_1", None)
                    attribute_data.pop("jarjestetaan_periaatteet_esillaolo_1", None)
        except KeyError as exc:
            pass

    def log_updates_attribute_data(self, attribute_data, project=None, prefix=""):
        project = project or self.instance
        if not project:
            raise ValueError("Can't update attribute data log if no project")

        user = self.context["request"].user
        instance_attribute_date = getattr(self.instance, "attribute_data", {})
        updated_attribute_values = {}

        for identifier, value in attribute_data.items():
            existing_value = instance_attribute_date.get(identifier, None)

            if not value and not existing_value:
                old_file = ProjectAttributeFile.objects \
                    .filter(
                        project=project,
                        archived_at=None,
                        attribute__identifier=identifier,
                    ).order_by("-created_at").first()
                if old_file:
                    existing_value = old_file.description

            if value != existing_value:
                updated_attribute_values[identifier] = {
                    "old": existing_value,
                    "new": value,
                }

        updated_attributes = Attribute.objects.filter(
            identifier__in=updated_attribute_values.keys()
        )

        geometry_attributes = []
        for attribute in updated_attributes:
            # Add additional checks for geometries since they are not actually stored
            # in the attribute_data but in their own model
            if attribute.value_type == Attribute.TYPE_GEOMETRY:
                geometry_attributes.append(attribute)
                continue

            values = updated_attribute_values[attribute.identifier]

            if attribute.value_type in [Attribute.TYPE_FIELDSET, Attribute.TYPE_INFO_FIELDSET]:
                for i, children in enumerate(values["new"]):
                    for k, v in dict(children).items():
                        self.log_updates_attribute_data(
                            {k: v},
                            project=project,
                            prefix=f"{prefix}{attribute.identifier}[{i}].",
                        )

            if attribute.value_type == Attribute.TYPE_CHOICE:
                if isinstance(values["new"], list):
                    values["new"] = [
                        value.identifier for value in values["new"]
                    ]
                else:
                    try:
                        values["new"] = values["new"].identifier
                    except AttributeError:
                        pass

            self._create_updates_log(
                attribute, project, user, values["new"], values["old"], prefix
            )

        for geometry_attribute in geometry_attributes:
            geometry_instance = ProjectAttributeMultipolygonGeometry.objects.filter(
                project=project, attribute=geometry_attribute
            ).first()
            new_geometry = attribute_data[geometry_attribute.identifier]
            if geometry_instance and geometry_instance.geometry != new_geometry:
                self._create_updates_log(geometry_attribute, project, user, None, None)

    def _get_labels(self, values, attribute):
        labels = {}

        for val in values:
            try:
                labels[val] = attribute.value_choices.get(identifier=val).value
            except AttributeValueChoice.DoesNotExist:
                pass

        return labels

    def _create_updates_log(self, attribute, project, user, new_value, old_value, prefix=""):
        new_value = json.loads(json.dumps(new_value, default=str))
        old_value = json.loads(json.dumps(old_value, default=str))
        labels = {}

        if attribute.value_type == Attribute.TYPE_CHOICE:
            if new_value:
                labels = {**labels, **self._get_labels(
                    new_value if type(new_value) is list else [new_value],
                    attribute,
                )}

            if old_value:
                labels = {**labels, **self._get_labels(
                    old_value if type(old_value) is list else [old_value],
                    attribute,
                )}

        entry = action.send(
            user,
            verb=verbs.UPDATED_ATTRIBUTE,
            action_object=attribute,
            target=project,
            attribute_identifier=prefix+attribute.identifier,
            old_value=old_value,
            new_value=new_value,
            labels=labels,
        )
        if attribute.broadcast_changes or project.phase_documents_creation_started:
            if not old_value and not new_value:
                change_string = ""
            else:
                old_value = old_value or "<tyhjä>"
                new_value = new_value or "<tyhjä>"
                change_string = f"\n{old_value} -> {new_value}"
            ProjectComment.objects.create(
                project=project,
                generated=True,
                content=f'{user.get_display_name()} päivitti "{attribute.name}" tietoa.{change_string}',
            )

        if attribute.value_type in [Attribute.TYPE_FILE, Attribute.TYPE_IMAGE] \
            and new_value is None:
            fieldset_path_str = prefix + attribute.identifier if prefix else None
            timestamp = entry[0][1].timestamp
            for old_file in ProjectAttributeFile.objects.filter(
                project=project,
                attribute=attribute,
                archived_at=None,
                fieldset_path_str=fieldset_path_str
            ):
                old_file.archived_at = timestamp
                old_file.save()

    def create_deadline_updates_log(self, deadline, project, user, old_date, new_date):
        old_value = json.loads(json.dumps(old_date, default=str))
        new_value = json.loads(json.dumps(new_date, default=str))

        if old_value != new_value:
            action.send(
                user,
                verb=verbs.UPDATED_DEADLINE,
                action_object=deadline,
                target=project,
                deadline_abbreviation=deadline.abbreviation,
                old_value=old_value,
                new_value=new_value,
            )


class SimpleProjectSerializer(serializers.ModelSerializer):
    user = serializers.SlugRelatedField(
        read_only=False, slug_field="uuid", queryset=get_user_model().objects.all()
    )
    user_email = serializers.SerializerMethodField()
    type = serializers.CharField(source="subtype.id")
    phase = serializers.CharField(source="phase.id")

    @extend_schema_field(OpenApiTypes.STR)
    def get_user_email(self, project):
        return project.user.email

    class Meta:
        model = Project
        fields = [
            "user",
            "user_email",
            "created_at",
            "modified_at",
            "name",
            "identifier",
            "pino_number",
            "type",
            "subtype",
            "attribute_data",
            "phase",
            "id",
            "public",
            "owner_edit_override",
            "archived",
            "onhold",
            "create_principles",
            "create_draft",
            "type",
            "created_at",
            "modified_at",
        ]


class ProjectSnapshotSerializer(ProjectSerializer):
    user = serializers.SerializerMethodField()
    name = serializers.SerializerMethodField()
    pino_number = serializers.SerializerMethodField()
    create_principles = serializers.SerializerMethodField()
    create_draft = serializers.SerializerMethodField()
    subtype = serializers.SerializerMethodField()
    phase = serializers.SerializerMethodField()

    class Meta:
        model = Project
        fields = [
            "user",
            "created_at",
            "modified_at",
            "name",
            "identifier",
            "pino_number",
            "type",
            "subtype",
            "attribute_data",
            "phase",
            "id",
            "deadlines",
            "create_principles",
            "create_draft",
            "_metadata",
        ]
        read_only_fields = fields

    def _get_static_property(self, project, static_property):
        attribute_data = self.get_attribute_data(project)
        try:
            identifier = \
                Attribute.objects.get(static_property=static_property).identifier
            return attribute_data[identifier]
        except (Attribute.DoesNotExist, KeyError):
            return getattr(project, static_property)

    def get_user(self, project):
        value = getattr(project, "user")
        if value:
            return value.uuid

        return self._get_static_property(project, "user")  # .uuid

    def get_name(self, project):
        return self._get_static_property(project, "name")

    def get_pino_number(self, project):
        return self._get_static_property(project, "pino_number")

    def get_create_principles(self, project):
        return self._get_static_property(project, "create_principles")

    def get_create_draft(self, project):
        return self._get_static_property(project, "create_draft")

    def get_subtype(self, project):
        try:
            return ProjectPhaseLog.objects.filter(
                created_at__lte=self._get_snapshot_date(project),
                project=project
            ).order_by("-created_at").first().phase.project_subtype.id
        except (ProjectPhaseLog.DoesNotExist, AttributeError):
            return project.subtype.id

    def get_phase(self, project):
        try:
            return ProjectPhaseLog.objects.filter(
                created_at__lte=self._get_snapshot_date(project),
                project=project
            ).order_by("-created_at").first().phase.id
        except (ProjectPhaseLog.DoesNotExist, AttributeError):
            return project.phase.id

    def get_deadlines(self, project):
        snapshot = self._get_snapshot_date(project)

        actions = (
            project.target_actions.filter(
                verb=verbs.UPDATED_DEADLINE,
                timestamp__lte=snapshot,
            )
            .order_by(
                "action_object_content_type", "action_object_object_id", "-timestamp"
            )
            .distinct("action_object_content_type", "action_object_object_id")
            .prefetch_related("actor")
        )

        return [
            {
                "date": _action.data.get("new_value"),
                "abbreviation": _action.data.get("deadline_abbreviation")
            }
            for _action in actions
            if _action.data.get("new_value") is not None
        ]


class AdminProjectSerializer(ProjectSerializer):
    def get_fields(self):
        fields = super(AdminProjectSerializer, self).get_fields()
        request = self.context.get('request', None)

        fields["archived"] = serializers.BooleanField(
            allow_null=True, required=False,
        )
        fields["public"] = serializers.BooleanField(
            allow_null=True, required=False,
        )
        fields["owner_edit_override"] = serializers.BooleanField(
            allow_null=True, required=False,
        )
        fields["onhold"] = serializers.BooleanField(
            allow_null=True, required=False,
        )

        return fields


class CommonProjectPhaseSerializer(serializers.ModelSerializer):
    class Meta:
        model = CommonProjectPhase
        fields = [
            "name",
            "color",
            "color_code",
        ]


class ProjectPhaseSerializer(serializers.ModelSerializer):
    project_type = serializers.SerializerMethodField()

    class Meta:
        model = ProjectPhase
        fields = [
            "id",
            "project_type",
            "project_subtype",
            "name",
            "color",
            "color_code",
            "list_prefix",
            "index",
        ]

    @extend_schema_field(OpenApiTypes.INT)
    def get_project_type(self, project):
        return project.project_type.pk


class ProjectSubtypeSerializer(serializers.ModelSerializer):
    project_type = serializers.SerializerMethodField()

    class Meta:
        model = ProjectSubtype
        fields = [
            "id",
            "project_type",
            "name",
            "index",
        ]

    @extend_schema_field(OpenApiTypes.INT)
    def get_project_type(self, project):
        return project.project_type.pk


class FieldsetPathField(serializers.JSONField):
    def to_representation(self, value):
        return [
            {
                "parent": i["parent"].identifier,
                "index": i["index"],
            }
            for i in value
        ]


class ProjectFileSerializer(serializers.ModelSerializer):
    file = serializers.FileField(use_url=True)
    attribute = serializers.SlugRelatedField(
        slug_field="identifier",
        queryset=Attribute.objects.filter(
            value_type__in=[Attribute.TYPE_IMAGE, Attribute.TYPE_FILE]
        ),
    )
    project = serializers.PrimaryKeyRelatedField(queryset=Project.objects.all())
    fieldset_path = FieldsetPathField(binary=True, required=False)

    class Meta:
        model = ProjectAttributeFile
        fields = ["file", "attribute", "project", "description", "fieldset_path"]

    @staticmethod
    def _validate_attribute(attribute: Attribute, project: Project):
        # Check if the attribute is part of the project
        try:
            # Field belongs to a fieldset
            project_has_attribute = bool(ProjectPhaseSectionAttribute.objects.filter(
                section__phase__project_subtype__project_type=project.type,
                attribute=attribute.fieldset_attribute_target.get().attribute_source,
            ).count)
        except ObjectDoesNotExist:
            project_has_attribute = bool(ProjectPhaseSectionAttribute.objects.filter(
                section__phase__project_subtype__project_type=project.type,
                attribute=attribute,
            ).count())

        if not project_has_attribute:
            # Using the same error message as SlugRelatedField
            raise ValidationError(_("Object with {slug_name}={value} does not exist."))

    def validate(self, attrs: dict):
        self._validate_attribute(attrs["attribute"], attrs["project"])

        return attrs

    def create(self, validated_data):
        fieldset_path = validated_data.pop("fieldset_path", [])
        attribute = validated_data["attribute"]

        # Save new path as a string for easier querying
        if fieldset_path:
            path_string = ".".join([
                f"{loc['parent']}[{loc['index']}]"
                for loc in fieldset_path
            ]) + f".{attribute.identifier}"
            validated_data["fieldset_path_str"] = path_string

        else:
            path_string = None

        old_files = list(ProjectAttributeFile.objects.filter(
            project=validated_data["project"],
            attribute=attribute,
            archived_at=None,
            fieldset_path_str=path_string,
        ).order_by("-created_at"))

        try:
            old_file = old_files[0]
            old_value = old_file.description
        except (AttributeError, IndexError):
            old_file = None
            old_value = None

        new_file = super().create(validated_data)
        new_value = new_file.description

        # Create related fieldset path objects
        for i, location in enumerate(fieldset_path):
            ProjectAttributeFileFieldsetPathLocation.objects.create(
                target=new_file,
                index=i,
                child_index=location["index"],
                parent_fieldset=Attribute.objects.get(
                    identifier=location["parent"],
                ),
            )

        if old_value != new_value or old_file and old_file.file != new_file.file:
            log_identifier = \
                path_string or \
                validated_data["attribute"].identifier
            entry = action.send(
                self.context["request"].user or validated_data["project"].user,
                verb=verbs.UPDATED_ATTRIBUTE,
                action_object=attribute,
                target=validated_data["project"],
                attribute_identifier=log_identifier,
                new_value=new_value,
                old_value=old_value,
            )
            timestamp = entry[0][1].timestamp
        else:
            timestamp = datetime.datetime.now()

        for old_file in old_files:
            old_file.archived_at = timestamp
            old_file.save()

        return new_file
