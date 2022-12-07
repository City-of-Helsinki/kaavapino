import copy
import datetime
import re
import logging
import numpy as np
import requests
from typing import List, NamedTuple, Type, Any, Union, Optional

from actstream import action
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.exceptions import ObjectDoesNotExist
from django.core.serializers.json import DjangoJSONEncoder, json
from django.db import transaction
from django.db.models import Prefetch, Q, QuerySet
from django.utils.translation import gettext_lazy as _
from drf_spectacular.utils import extend_schema_field, inline_serializer
from drf_spectacular.types import OpenApiTypes
from rest_framework import serializers, status
from rest_framework.request import Request
from rest_framework.exceptions import ValidationError, NotFound, ParseError
from rest_framework.response import Response
from rest_framework.serializers import Serializer
from rest_framework_gis.fields import GeometryField

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
    ProjectPhaseDeadlineSection,
    ProjectFloorAreaSection,
    ProjectAttributeFile,
    ProjectDeadline,
    Attribute,
    AttributeValueChoice,
    ProjectPhaseSectionAttribute,
    ProjectComment,
    Deadline,
    DeadlineDistance,
    DeadlineDateCalculation,
    ProjectAttributeFileFieldsetPathLocation,
    OverviewFilter,
    OverviewFilterAttribute,
    DocumentTemplate,
    DocumentLinkFieldSet,
)
from projects.models.project import ProjectAttributeMultipolygonGeometry
from projects.permissions.media_file_permissions import (
    has_project_attribute_file_permissions,
)
from projects.serializers.utils import _set_fieldset_path
from projects.serializers.fields import AttributeDataField
from projects.serializers.document import DocumentTemplateSerializer
from projects.serializers.section import create_section_serializer
from projects.serializers.deadline import DeadlineSerializer
from sitecontent.models import ListViewAttributeColumn
from users.models import User
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

    @extend_schema_field(DeadlineSerializer)
    def get_deadline(self, projectdeadline: ProjectDeadline) -> dict[str, Any]:
        return DeadlineSerializer(
            projectdeadline.deadline
        ).data

    def _resolve_distance_conditions(self, distance: DeadlineDistance, project: Project) -> bool:
        if distance.conditions.count() == 0:
            return True

        attribute: Attribute
        for attribute in distance.conditions.all():
            if project.attribute_data.get(attribute.identifier):
                return True

        return False

    @extend_schema_field(OpenApiTypes.BOOL)
    def get_is_under_min_distance_next(self, projectdeadline: ProjectDeadline) -> bool:
        if not projectdeadline.date:
            return False

        next_deadlines: QuerySet[DeadlineDistance] = projectdeadline.deadline.distances_to_next.all()\
            .select_related("deadline", "deadline__date_type")
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
    def get_is_under_min_distance_previous(self, projectdeadline: ProjectDeadline) -> bool:
        if not projectdeadline.date:
            return False

        prev_deadlines: QuerySet[DeadlineDistance] = projectdeadline.deadline.distances_to_previous.all()\
            .select_related("previous_deadline", "previous_deadline__date_type")\
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
    def get_past_due(self, projectdeadline: ProjectDeadline) -> bool:
        return len([
            dl for dl in projectdeadline.project.deadlines.filter(
                deadline__index__lte=projectdeadline.deadline.index,
                date__lt=datetime.date.today(),
            ).select_related("project", "deadline", "deadline__confirmation_attribute")
            if not dl.confirmed
        ]) > 0

    @extend_schema_field(OpenApiTypes.BOOL)
    def get_out_of_sync(self, projectdeadline: ProjectDeadline) -> bool:
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


class ProjectOverviewSerializer(serializers.ModelSerializer):
    user = serializers.SlugRelatedField(
        slug_field="uuid",
        queryset=get_user_model().objects.all(),
    )
    user_name = serializers.SerializerMethodField()
    subtype = serializers.SerializerMethodField()
    phase = serializers.SerializerMethodField()

    def get_user_name(self, project: Project) -> str:
        first_name: str = project.user.first_name
        last_name: str = project.user.last_name

        return " ".join([first_name, last_name])

    def get_phase(self, project: Project) -> dict[str, Any]:
        return ProjectPhaseSerializer(project.phase).data

    def get_subtype(self, project: Project) -> dict[str, Any]:
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

    def _get_filters(self, overview_filter: OverviewFilter, filters: str) -> bool:
        return bool(overview_filter.attributes.filter(**{filters: True}).count())

    @extend_schema_field(OpenApiTypes.BOOL)
    def get_filters_by_subtype(self, overview_filter: OverviewFilter) -> bool:
        return self._get_filters(overview_filter, "filters_by_subtype")

    @extend_schema_field(OpenApiTypes.BOOL)
    def get_filters_on_map(self, overview_filter: OverviewFilter) -> bool:
        return self._get_filters(overview_filter, "filters_on_map")

    @extend_schema_field(OpenApiTypes.BOOL)
    def get_filters_floor_area(self, overview_filter: OverviewFilter) -> bool:
        return self._get_filters(overview_filter, "filters_floor_area")

    def get_value_type(self, overview_filter: OverviewFilter) -> Optional[str]:
        # It's never validated one filter only contains one type of values;
        # trusting the admin user for now
        if overview_filter.attributes.first():
            return overview_filter.attributes.first().attribute.value_type

        return None

    @extend_schema_field(OpenApiTypes.BOOL)
    def get_accepts_year(self, overview_filter: OverviewFilter) -> bool:
        attr: OverviewFilterAttribute
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
    def get_choices(self, overview_filter: OverviewFilter) -> list[dict[str, str]]:
        choices: dict[str, str] = {}

        attr: OverviewFilterAttribute
        for attr in overview_filter.attributes.all().prefetch_related("attribute__value_choices"):
            choice: AttributeValueChoice
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

    def get_project_count(self, phase: ProjectPhase) -> int:
        return phase.projects.filter(
            self.context.get("query", Q()),
            public=True,
        ).count()

    def get_projects(self, phase: ProjectPhase) -> dict[str, Any]:
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

    def get_phases(self, subtype: ProjectSubtype) -> dict[str, Any]:
        return ProjectPhaseOverviewSerializer(
            subtype.phases.all().select_related("project_subtype", "project_subtype__project_type", "common_project_phase"),
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

    def get_geoserver_data(self, project: Project) -> Optional[dict[str, Any]]:
        identifier = project.attribute_data.get("hankenumero")
        if identifier:
            url = f"{settings.KAAVOITUS_API_BASE_URL}/geoserver/v1/suunnittelualue/{identifier}"

            if cache.get(url) is not None:
                response = cache.get(url)
            else:
                response = requests.get(
                    url,
                    headers={"Authorization": f"Token {settings.KAAVOITUS_API_AUTH_TOKEN}"},
                )
                if response.status_code == 200:
                    cache.set(url, response, 86400)  # 1 day
                elif response.status_code == 404:
                    cache.set(url, response, 900)  # 15 minutes
                elif response.status_code >= 500:
                    log.error("Kaavoitus-api connection error: {} {}".format(
                        response.status_code,
                        response.text
                    ))
                else:
                    cache.set(url, response, 180)  # 3 minutes

            if response.status_code == 200:
                return response.json()

        return None

    @extend_schema_field(OpenApiTypes.STR)
    def get_user_name(self, project: Project) -> str:
        first_name: str = project.user.first_name
        last_name: str = project.user.last_name

        return " ".join([first_name, last_name])

    # @extend_schema_field(ProjectPhaseSerializer)
    def get_phase(self, project: Project) -> dict[str, Any]:
        return ProjectPhaseSerializer(project.phase).data

    # @extend_schema_field(ProjectSubtypeSerializer)
    def get_subtype(self, project: Project) -> dict[str, Any]:
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
    attribute_data = AttributeDataField(allow_null=True, required=False)
    type = serializers.SerializerMethodField()
    phase_start_date = serializers.SerializerMethodField()
    deadlines = serializers.SerializerMethodField()

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
            "public",
            "owner_edit_override",
            "archived",
            "onhold",
            "create_principles",
            "create_draft",
            "phase_start_date",
            "deadlines",
        ]

    @extend_schema_field(OpenApiTypes.INT)
    def get_type(self, project: Project) -> int:
        return project.type.pk

    @extend_schema_field(OpenApiTypes.DATE)
    def get_phase_start_date(self, project: Project) -> Optional[datetime.date]:
        try:
            return project.deadlines \
                .filter(deadline__phase=project.phase) \
                .order_by("deadline__index").first().date
        except AttributeError:
            return None

    def get_attribute_data(self, project: Project) -> dict[str, Any]:
        static_properties: list[str] = [
            "user",
            "name",
            "public",
            "pino_number",
            "create_principles",
            "create_draft",
        ]
        return_data: dict[str, Any] = {}
        attrs: list[ListViewAttributeColumn] = \
            self.context["listview_attribute_columns"] \
            if self.context.__contains__("listview_attribute_columns") \
            else ListViewAttributeColumn.objects.all().select_related("attribute")
        attribute_data: dict[str, Any] = getattr(project, "attribute_data", {})
        for attr in attrs:
            identifier: str = attr.attribute.identifier
            value: Any = attribute_data.get(identifier)
            if attr.attribute.static_property in static_properties:
                return_data[identifier] = getattr(
                    project, attr.attribute.static_property
                )
            elif value:
                return_data[identifier] = value

        return return_data

    @extend_schema_field(ProjectDeadlineSerializer(many=True))
    def get_deadlines(self, project: Project) -> list[dict[str, Any]]:
        project_schedule_cache = self.context["project_schedule_cache"]
        return project_schedule_cache.get(project.pk, [])


class ProjectExternalDocumentSerializer(serializers.Serializer):
    document_name = serializers.SerializerMethodField()
    link = serializers.SerializerMethodField()

    def _get_field_as_string(self, fieldset_item: dict[str, Any], attribute: Attribute) -> str:
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
    def get_document_name(self, fieldset_item: dict[str, Any]) -> str:
        name_attribute: Attribute = self.context["document_fieldset"]. \
            document_name_attribute
        custom_name_attribute: Attribute = self.context["document_fieldset"]. \
            document_custom_name_attribute

        name: str = self._get_field_as_string(
            fieldset_item, name_attribute
        )
        custom_name: str = self._get_field_as_string(
            fieldset_item, custom_name_attribute
        )

        return custom_name or name

    @extend_schema_field(OpenApiTypes.STR)
    def get_link(self, fieldset_item: dict[str, str]) -> str:
        return fieldset_item.get(
            self.context["document_fieldset"].document_link_attribute.identifier
        )


class ProjectExternalDocumentSectionSerializer(serializers.Serializer):
    section_name = serializers.SerializerMethodField()
    documents = serializers.SerializerMethodField()

    @extend_schema_field(OpenApiTypes.STR)
    def get_section_name(self, *args) -> str:
        return self.context["section"].name

    @extend_schema_field(ProjectExternalDocumentSerializer(many=True))
    def get_documents(self, project: Project) -> list[dict[str, Any]]:
        section = self.context["section"]
        fields: list[dict[str, Any]] = []

        document_fieldset: DocumentLinkFieldSet
        for document_fieldset in section.documentlinkfieldset_set.all():
            fieldset_data: list = project.attribute_data.get(
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
    attribute_data = AttributeDataField(allow_null=True, required=False)
    type = serializers.SerializerMethodField()
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
            "created_at",
            "modified_at",
            "phase_documents_created",
            "phase_documents_creation_started",
            "project_card_document",
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

    def get_geoserver_data(self, project: Project) -> Optional[dict[str, Any]]:
        identifier: str = project.attribute_data.get("hankenumero")
        if identifier:
            url = f"{settings.KAAVOITUS_API_BASE_URL}/geoserver/v1/suunnittelualue/{identifier}"

            response = requests.get(
                url,
                headers={"Authorization": f"Token {settings.KAAVOITUS_API_AUTH_TOKEN}"},
            )
            if response.status_code == 200:
                cache.set(url, response, 86400)  # 1 day
            elif response.status_code == 404:
                cache.set(url, response, 900)  # 15 minutes
            elif response.status_code >= 500:
                log.error("Kaavoitus-api connection error: {} {}".format(
                    response.status_code,
                    response.text
                ))
            else:
                cache.set(url, response, 180)  # 3 minutes

            if response.status_code == 200:
                return response.json()

        return None

    def _get_snapshot_date(self, project: Project) -> Optional[datetime.date]:
        query_params: dict[str, Any] = getattr(self.context["request"], "GET", {})
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

    def get_fields(self) -> dict[str, Any]:
        fields: dict[str, Any] = super(ProjectSerializer, self).get_fields()
        request: Request = self.context.get('request', None)

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

    def get_attribute_data(self, project: Project) -> dict[str, Any]:
        snapshot: datetime.date = self._get_snapshot_date(project)

        if snapshot:
            attribute_data: dict[str, Any] = {
                k: v["new_value"]
                for k, v in self._get_updates(project, Attribute.objects.all(),
                                              cutoff=snapshot, request=self.context.get('request', None)).items()
            }
        else:
            attribute_data: dict[str, Any] = getattr(project, "attribute_data", {})

        self._set_file_attributes(attribute_data, project, snapshot)

        if snapshot:
            try:
                subtype: ProjectSubtype = ProjectPhaseLog.objects.filter(
                    created_at__lte=self._get_snapshot_date(project),
                    project=project
                ).order_by("-created_at").first().phase.project_subtype
            except AttributeError:
                subtype: ProjectSubtype = project.phase.project_subtype
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

        static_properties: list[str] = [
            "user",
            "name",
            "public",
            "pino_number",
            "create_principles",
            "create_draft",
        ]

        if not snapshot:
            # Prevent making database calls within for-loop by getting attributes from database here
            attributes: QuerySet[Attribute] = Attribute.objects.filter(static_property__in=static_properties)
            for static_property in static_properties:
                attribute = next(filter(lambda attr: attr.static_property == static_property, attributes), None)
                if attribute:
                    value = getattr(project, static_property)

                    if attribute.value_type == Attribute.TYPE_USER:
                        value = value.uuid

                    attribute_data[attribute.identifier] = value

        return attribute_data

    @extend_schema_field(OpenApiTypes.INT)
    def get_type(self, project: Project) -> int:
        return project.type.pk

    @extend_schema_field(ProjectDeadlineSerializer(many=True))
    def get_deadlines(self, project: Project) -> dict[str, Any]:
        project_schedule_cache: dict[int, dict[str, Any]] = cache.get("serialized_project_schedules", {})
        deadlines: QuerySet[Deadline] = project.deadlines.filter(deadline__subtype=project.subtype)\
            .select_related("deadline", "project")\
            .prefetch_related("project__subtype", "project__deadlines", "project__deadlines__deadline",
                              "project__deadlines__project", "deadline__distances_to_previous",
                              "deadline__distances_to_next", "deadline__attribute", "deadline__phase",
                              "deadline__subtype", "deadline__date_type", "deadline__phase__project_subtype")
        schedule = project_schedule_cache.get(project.pk)
        if self.context.get('should_update_deadlines') or not schedule:
            schedule: dict[str, Any] = ProjectDeadlineSerializer(
                deadlines,
                many=True,
                allow_null=True,
                required=False,
            ).data

        project_schedule_cache[project.pk] = schedule
        cache.set("serialized_project_schedules", project_schedule_cache, None)
        return schedule

    @extend_schema_field(serializers.ListSerializer(child=serializers.CharField()))
    def get_generated_deadline_attributes(self, project: Project) -> list[str]:
        return [
            dl.deadline.attribute.identifier
            for dl in project.deadlines.filter(generated=True).select_related("deadline__attribute")
            if dl.deadline.attribute
        ]

    @extend_schema_field(serializers.ListSerializer(child=serializers.CharField()))
    def get_deadline_attributes(self, project: Project) -> list[str]:
        return [
            dl.deadline.attribute.identifier
            for dl in project.deadlines.filter().select_related("deadline__attribute")
            if dl.deadline.attribute
        ]

    @extend_schema_field(OpenApiTypes.BOOL)
    def get_phase_documents_created(self, project: Project) -> bool:
        return project.phase_documents_created

    def get_project_card_document(self, project: Project) -> dict[str, Any]:
        template: DocumentTemplate = DocumentTemplate.objects.filter(project_card_default_template=True).first()
        if not template:
            return None

        return DocumentTemplateSerializer(template, many=False, context={
            "project": project,
            "request": self.context.get("request")},
        ).data

    @extend_schema_field(OpenApiTypes.BOOL)
    def get_phase_documents_creation_started(self, project: Project) -> bool:
        return project.phase_documents_creation_started

    def _set_file_attributes(self, attribute_data: dict[str, Any], project: Project, snapshot: Optional[datetime.date]):
        request = self.context["request"]
        if snapshot:
            attribute_files: QuerySet[ProjectAttributeFile] = ProjectAttributeFile.objects \
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
            attribute_files: QuerySet[ProjectAttributeFile] = ProjectAttributeFile.objects \
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
        file_attributes: dict[str, Union[dict, list]] = {}
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

    def get__metadata(self, project: Project) -> dict[str, Any]:
        list_view: bool = self.context.get("action", None) == "list"
        attributes: QuerySet[Attribute] = Attribute.objects.all().prefetch_related("key_attribute", "fieldsets", "fieldset_attributes"
        )  # perform further filtering of attributes within methods
        metadata: dict[str, Any] = {
            "users": self._get_users(project, attributes, list_view=list_view),
            "personnel": self._get_personnel(project, attributes, list_view=list_view),
        }
        query_params = getattr(self.context["request"], "GET", {})
        snapshot_param = query_params.get("snapshot")
        if not list_view and not snapshot_param:
            metadata["updates"] = self._get_updates(project, attributes, cutoff=None, request=self.context.get('request', None))

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
    def _get_users(project: Project, attributes: list[Attribute], list_view=False) -> list[dict[str, Any]]:
        users: list[User] = [project.user]

        if not list_view:
            user_attribute_ids: set[str] = set()
            for attribute in filter(lambda a: a.value_type in [Attribute.TYPE_USER, Attribute.TYPE_FIELDSET], attributes):
                if attribute.value_type == Attribute.TYPE_FIELDSET:
                    fieldset_user_identifiers: QuerySet[Attribute] = attribute.fieldset_attributes\
                        .filter(value_type=Attribute.TYPE_USER)\
                        .prefetch_related("identifier")\
                        .values_list("identifier", flat=True)
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
    def _get_personnel(project: Project,
                       attributes: list[Attribute],
                       list_view: bool = False
                       ) -> Union[list[dict[str, str]], Response]:
        if list_view:
            return []

        flat_data: dict[str, list] = get_flat_attribute_data(project.attribute_data, {})

        ids: list[str] = []

        for attr in filter(lambda a: a.value_type == Attribute.TYPE_PERSONNEL, attributes):
            value = flat_data.get(attr.identifier)

            if not value:
                continue
            elif type(value) is list:
                ids += set(value)
            else:
                ids.append(value)

        return_values: list[dict[str, str]] = []

        for id in set(ids):
            url = f"{settings.GRAPH_API_BASE_URL}/v1.0/users/{id}"
            response = cache.get(url)
            if not response:
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

                cache.set(url, response, 60)

            data = PersonnelSerializer(response.json()).data
            return_values.append({"id": id, "name": data["name"]})

        return return_values

    @staticmethod
    def _get_fieldset_attribute_values(project: Project,
                                       fieldset_attribute: Attribute,
                                       fieldset_identifiers: QuerySet[Attribute]
                                       ) -> set[Any]:
        values: set[Any] = set()
        for entry in project.attribute_data[fieldset_attribute.identifier]:
            for identifier in fieldset_identifiers:
                value = entry.get(identifier, None)
                if value:
                    values.add(value)

        return values

    @staticmethod
    def _get_updates(project: Project,
                     attributes: QuerySet[Attribute],
                     cutoff: Optional[datetime.date] = None,
                     request: Request = None
                     ) -> dict[str, dict[str, Any]]:

        def get_editable(attribute: Attribute) -> bool:
            from users.models import privilege_as_int

            if not request or not request.user:
                return False

            user: User = request.user
            owner: bool = request.query_params.get("owner", False)
            is_owner: bool = \
                owner in ["1", "true", "True"] or \
                project and project.user == user

            privilege: int = privilege_as_int(user.privilege)

            # owner can edit owner-editable fields regardless of their role
            if is_owner and attribute.owner_editable:
                return True
            # check privilege for others
            elif attribute.edit_privilege and \
                privilege >= privilege_as_int(attribute.edit_privilege):
                return True
            else:
                return False

        def get_attribute_schema(attribute_list: list[Attribute], schema: dict[str, dict[str, Any]]) -> None:
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
                        attribute: Attribute = next(filter(lambda a: a.identifier == identifier, attributes), None)
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

        def get_schema(attribute_identifier: str, data: dict[str, list], labels) -> dict[str, dict[str, Any]]:
            schema: dict[str, dict[str, Any]] = {}

            attribute: Attribute = next(filter(lambda a: a.identifier == attribute_identifier, attributes), None)
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

        updates: dict[str, dict[str, Any]] = {}
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

    def should_validate_attributes(self) -> bool:
        # Always validate if not explicitly turned off
        if "validate_attribute_data" in self.context["request"].data:
            validate_field_data = self.context["request"].data.get(
                "validate_attribute_data", False
            )
        else:
            validate_field_data = True

        return serializers.BooleanField().to_internal_value(validate_field_data)

    def _get_keys(self) -> list[str]:
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
        preview: dict[Deadline, datetime.date],
        validation: bool = True,
    ) -> List[SectionData]:
        sections: list[SectionData] = []
        sections_to_serialize: QuerySet[ProjectPhaseSection] = phase.sections \
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
            self,
            floor_area_sections: QuerySet[ProjectFloorAreaSection],
            preview: dict[Deadline, datetime.date],
            validation: bool = True
    ) -> List[SectionData]:
        sections: list[SectionData] = []
        sections_to_serialize: QuerySet[ProjectFloorAreaSection] = floor_area_sections \
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

    def generate_schedule_sections_data(
            self,
            phase: ProjectPhase,
            preview: dict[Deadline, datetime.date],
            validation: bool = True
    ) -> list[SectionData]:
        sections: list[SectionData] = []
        deadline_sections: QuerySet[ProjectPhaseDeadlineSection] = phase.deadline_sections.filter(
            attributes__identifier__in=self._get_keys()
        )
        for section in deadline_sections:
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

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        archived: bool = attrs.get('archived')
        was_archived: bool = self.instance and self.instance.archived

        if archived is not False and was_archived:
            raise ValidationError(
                {"phase": _("Archived projects cannot be edited")}
            )

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

    def _get_should_update_deadlines(self,
                                     subtype_changed: bool,
                                     instance: Project,
                                     attribute_data: dict[str, Any]
                                     ) -> bool:
        if subtype_changed:
            should_update_deadlines = False
        elif instance:
            attr_identifiers: list[str] = list(attribute_data.keys())
            should_update_deadlines = bool(
                instance.deadlines.prefetch_related("deadline").filter(
                    deadline__attribute__identifier__in=attr_identifiers
                ).count()
            )

            if not should_update_deadlines:
                should_update_deadlines: bool = bool(
                    Deadline.objects.filter(
                        subtype=instance.subtype,
                        condition_attributes__identifier__in=attr_identifiers,
                    ).count()
                )

            if not should_update_deadlines:
                should_update_deadlines = bool(DeadlineDateCalculation.objects.filter(
                    deadline__project_deadlines__project=instance
                ).filter(
                    Q(conditions__identifier__in=attr_identifiers) | \
                    Q(not_conditions__identifier__in=attr_identifiers) | \
                    Q(datecalculation__base_date_attribute__identifier__in=attr_identifiers) | \
                    Q(datecalculation__attributes__attribute__identifier__in=attr_identifiers)
                ).count())

        return should_update_deadlines

    def _validate_attribute_data(self,
                                 attribute_data: dict[str, Any],
                                 validate_attributes: dict[str, Attribute],
                                 user: User,
                                 owner_edit_override: bool
                                 ) -> dict[str, Any]:
        static_property_attributes: dict[str, Attribute] = {}
        if self.instance:
            static_properties: list[str] = [
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

        # Get serializers for all sections in all phases
        sections_data: list[SectionData] = []
        current_phase: ProjectPhase = getattr(self.instance, "phase", None)
        subtype: ProjectSubtype = getattr(self.instance, "subtype", None) or \
            validate_attributes.get("subtype")
            # TODO: check if this subtype should be an attribute of phase object instead
            #validate_attributes.get("phase").project_subtype
        should_validate: bool = self.should_validate_attributes()
        min_phase_index: int = current_phase.index if current_phase else 1

        try:
            is_owner: bool = self.context["request"].user == self.user
            if owner_edit_override and is_owner:
                min_phase_index = 1
        except AttributeError:
            pass

        should_update_deadlines: bool = self._get_should_update_deadlines(
            False, self.instance, attribute_data,
        )
        preview: dict[Deadline, datetime.date] = None
        if self.instance and should_update_deadlines:
            preview = self.instance.get_preview_deadlines(
                attribute_data,
                subtype,
            )
        # Phase index 1 is always editable
        # Otherwise only current phase and upcoming phases are editable
        phase: ProjectPhase
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

        # Confirmed deadlines can't be edited
        confirmed_deadlines: list[str] = [
            dl.deadline.attribute.identifier for dl in self.instance.deadlines.all().select_related("deadline", "project", "deadline__confirmation_attribute")
            if dl.confirmed and dl.deadline.attribute
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

        invalid_identifiers: list[str] = []
        files_to_archive: list[tuple[str, ProjectAttributeFile]] = []
        for identifier in unusual_identifiers:
            try:
                attribute_file = ProjectAttributeFile.objects.get(
                    archived_at=None,
                    fieldset_path_str=identifier,
                    project=self.instance,
                )
                files_to_archive.append((identifier, attribute_file))

            except (ProjectAttributeFile.DoesNotExist, Attribute.DoesNotExist):
                invalid_identifiers.append(identifier)

        if len(invalid_identifiers):
            invalids: list[str] = [f"{key}: {_('Cannot edit field.')}" for key in invalid_identifiers]
            log.warn(", ".join(invalids))

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
            for dl in ProjectDeadline.objects.filter(
                project=self.instance,
                deadline__attribute__identifier__in=valid_attributes.keys()
            ):
                dl.generated = False
                dl.save()

        return {**static_property_attributes, **valid_attributes}

    def _validate_public(self, attrs: dict[str, Any]) -> bool:
        public: bool = attrs.get("public")

        # Do not validate if this is a new project
        if not self.instance:
            return public or True

        # A project is always public if it has exited the starting phase
        try:
            phase_index: int = attrs["phase"].index
        except KeyError:
            phase_index: int = self.instance.phase.index

        if not self.instance.public and (phase_index > 1):
            return True

        if public is None:
            return self.instance.public

        return public

    def _validate_owner_edit_override(self, attrs: dict[str, Any]) -> bool:
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

    def validate_phase(self, phase: ProjectPhase, subtype_id: int = None) -> ProjectPhase:
        if not subtype_id:
            try:
                subtype_id = int(self.get_initial()["subtype"])
            except KeyError:
                subtype_id = self.instance.subtype.pk

        def _get_relative_phase(phase: ProjectPhase, offset: int):
            return phase.project_subtype.phases.get(index=phase.index + offset)

        offset: int = None

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

    def _validate_phase(self, attrs: dict[str, Any]) -> ProjectPhase:
        try:
            return attrs["phase"]
        except KeyError:
            return self.validate_phase(
                ProjectPhase.objects.get(pk=self.instance.phase.pk),
                subtype_id=attrs["subtype"].id
            )

    def validate_user(self, user: User) -> User:
        if not user.has_privilege('create'):
            raise ValidationError(
                {"user": _("Selected user does not have the required role")}
            )

        return user

    def create(self, validated_data: dict[str, Any]) -> Project:
        validated_data["phase"] = ProjectPhase.objects.filter(
            project_subtype=validated_data["subtype"]
        ).first()

        with transaction.atomic():
            self.context['should_update_deadlines'] = True
            attribute_data = validated_data.pop("attribute_data", {})
            attribute_data["kaavaprosessin_kokoluokka_readonly"] = validated_data["phase"].project_subtype.name
            try:
                attribute_data["projektityyppi"] = AttributeValueChoice.objects.get(value="Asemakaava")
            except:
                pass

            project: Project = super().create(validated_data)
            user: User = self.context["request"].user
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

            user: User = self.context["request"].user
            project.update_deadlines(user=user)
            dl: ProjectDeadline
            for dl in project.deadlines.all():
                self.create_deadline_updates_log(
                    dl.deadline, project, user, None, dl.date
                )

        return project

    def update(self, instance: Project, validated_data: dict[str, Any]) -> Project:
        attribute_data: dict[str, Any] = validated_data.pop("attribute_data", {})
        subtype: ProjectSubtype = validated_data.get("subtype")
        subtype_changed: bool = subtype is not None and subtype != instance.subtype
        phase: ProjectPhase = validated_data.get("phase")
        phase_changed: bool = phase is not None and phase != instance.phase
        should_generate_deadlines: bool = getattr(
            self.context["request"], "GET", {}
        ).get("generate_schedule") in ["1", "true", "True"]
        user: User = self.context["request"].user

        if phase_changed:
            ProjectPhaseLog.objects.create(
                project=instance,
                phase=phase,
                user=user,
            )

        should_update_deadlines: bool = self._get_should_update_deadlines(
            subtype_changed, instance, attribute_data,
        )
        self.context['should_update_deadlines'] = \
            should_update_deadlines or should_generate_deadlines

        with transaction.atomic():
            self.log_updates_attribute_data(attribute_data)
            try:
                attribute_data["projektityyppi"] = AttributeValueChoice.objects.get(value="Asemakaava")
            except:
                pass
            if attribute_data:
                instance.update_attribute_data(attribute_data)

            project: Project = super(ProjectSerializer, self).update(instance, validated_data)

            old_deadlines: QuerySet[ProjectDeadline] = None
            if should_update_deadlines or should_generate_deadlines:
                old_deadlines = project.deadlines.all().select_related("deadline")

            if should_generate_deadlines:
                cleared_attributes: dict[str, None] = {
                    project_dl.deadline.attribute.identifier: None
                    for project_dl in project.deadlines.all().select_related("deadline", "deadline__attribute")
                    if project_dl.deadline.attribute
                }
                project.update_attribute_data(cleared_attributes)
                self.log_updates_attribute_data(cleared_attributes)
                project.deadlines.all().delete()
                project.update_deadlines(user=user)
            elif should_update_deadlines:
                project.update_deadlines(user=user)

            project.save()

            if old_deadlines:
                project_deadlines: QuerySet[ProjectDeadline] = project.deadlines.all().select_related("deadline")
                updated_deadlines = old_deadlines.union(project_deadlines)
                for dl in updated_deadlines:
                    project_deadline: ProjectDeadline = \
                        next(filter(lambda _dl: _dl.deadline == dl.deadline, project_deadlines), None)
                    new_date = project_deadline.date if project_deadline else None

                    old_deadline: ProjectDeadline = \
                        next(filter(lambda _dl: _dl.deadline == dl.deadline, old_deadlines), None)
                    old_date = old_deadline.date if old_deadline else None

                    self.create_deadline_updates_log(
                        dl.deadline, project, user, old_date, new_date
                    )

            return project

    def log_updates_attribute_data(self, attribute_data: dict[str, Any], project: Project = None, prefix: str = ""):
        project = project or self.instance
        if not project:
            raise ValueError("Can't update attribute data log if no project")

        user: User = self.context["request"].user
        instance_attribute_date: dict[str, Any] = getattr(self.instance, "attribute_data", {})
        updated_attribute_values: dict[str, Any] = {}

        for identifier, value in attribute_data.items():
            existing_value = instance_attribute_date.get(identifier, None)

            if not value and not existing_value:
                old_file: ProjectAttributeFile = ProjectAttributeFile.objects \
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

        updated_attributes: QuerySet[Attribute] = Attribute.objects.filter(
            identifier__in=updated_attribute_values.keys()
        )

        geometry_attributes: list[Attribute] = []
        for attribute in updated_attributes:
            # Add additional checks for geometries since they are not actually stored
            # in the attribute_data but in their own model
            if attribute.value_type == Attribute.TYPE_GEOMETRY:
                geometry_attributes.append(attribute)
                continue

            values: dict[str, Any] = updated_attribute_values[attribute.identifier]

            if attribute.value_type == Attribute.TYPE_FIELDSET:
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
            geometry_instance: ProjectAttributeMultipolygonGeometry =\
                ProjectAttributeMultipolygonGeometry.objects.filter(
                    project=project, attribute=geometry_attribute
                ).first()
            new_geometry = attribute_data[geometry_attribute.identifier]
            if geometry_instance and geometry_instance.geometry != new_geometry:
                self._create_updates_log(geometry_attribute, project, user, None, None)

    def _get_labels(self, values: list[str], attribute: Attribute) -> dict[str, str]:
        labels: dict[str, str] = {}

        for val in values:
            try:
                labels[val] = attribute.value_choices.get(identifier=val).value
            except AttributeValueChoice.DoesNotExist:
                pass

        return labels

    def _create_updates_log(self,
                            attribute: Attribute,
                            project: Project,
                            user: User,
                            new_value: str,
                            old_value: str,
                            prefix: str = ""
                            ) -> None:
        new_value: str = json.loads(json.dumps(new_value, default=str))
        old_value: str = json.loads(json.dumps(old_value, default=str))
        labels: dict[str, str] = {}

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

    def create_deadline_updates_log(self,
                                    deadline: Deadline,
                                    project: Project,
                                    user: User,
                                    old_date: datetime.date,
                                    new_date: datetime.date
                                    ) -> None:
        old_value: str = json.loads(json.dumps(old_date, default=str))
        new_value: str = json.loads(json.dumps(new_date, default=str))

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
    type = serializers.CharField(source="subtype.id")
    phase = serializers.CharField(source="phase.id")

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

    def _get_static_property(self, project: Project, static_property: str) -> Any:
        attribute_data: dict[str, Any] = self.get_attribute_data(project)
        try:
            identifier: str = \
                Attribute.objects.get(static_property=static_property).identifier
            return attribute_data[identifier]
        except (Attribute.DoesNotExist, KeyError):
            return getattr(project, static_property)

    def get_user(self, project: Project) -> str:
        value: User = getattr(project, "user")
        if value:
            return value.uuid

        return self._get_static_property(project, "user")  # .uuid

    def get_name(self, project: Project) -> str:
        return self._get_static_property(project, "name")

    def get_pino_number(self, project: Project) -> str:
        return self._get_static_property(project, "pino_number")

    def get_create_principles(self, project: Project) -> Any:
        return self._get_static_property(project, "create_principles")

    def get_create_draft(self, project: Project) -> Any:
        return self._get_static_property(project, "create_draft")

    def get_subtype(self, project: Project) -> int:
        try:
            return ProjectPhaseLog.objects.filter(
                created_at__lte=self._get_snapshot_date(project),
                project=project
            ).order_by("-created_at").first().phase.project_subtype.id
        except (ProjectPhaseLog.DoesNotExist, AttributeError):
            return project.subtype.id

    def get_phase(self, project: Project) -> int:
        try:
            return ProjectPhaseLog.objects.filter(
                created_at__lte=self._get_snapshot_date(project),
                project=project
            ).order_by("-created_at").first().phase.id
        except (ProjectPhaseLog.DoesNotExist, AttributeError):
            return project.phase.id

    def get_deadlines(self, project: Project) -> list[dict[str, Any]]:
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
    def get_fields(self) -> dict[str, Any]:
        fields: dict[str, Any] = super(AdminProjectSerializer, self).get_fields()
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
    def get_project_type(self, project: Project) -> int:
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
    def get_project_type(self, project: Project) -> int:
        return project.project_type.pk


class FieldsetPathField(serializers.JSONField):
    def to_representation(self, value: list[dict[str, Any]]) -> list[dict[str, Any]]:
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
    def _validate_attribute(attribute: Attribute, project: Project) -> None:
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

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        self._validate_attribute(attrs["attribute"], attrs["project"])

        return attrs

    def create(self, validated_data) -> None:
        fieldset_path: list[dict[str, Any]] = validated_data.pop("fieldset_path", [])
        attribute: Attribute = validated_data["attribute"]

        # Save new path as a string for easier querying
        if fieldset_path:
            path_string = ".".join([
                f"{loc['parent']}[{loc['index']}]"
                for loc in fieldset_path
            ]) + f".{attribute.identifier}"
            validated_data["fieldset_path_str"] = path_string

        else:
            path_string = None

        old_files: list[ProjectAttributeFile] = list(ProjectAttributeFile.objects.filter(
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
