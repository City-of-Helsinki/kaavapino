import pytz
import csv
from datetime import datetime, timedelta
import time
import logging

from django.contrib.postgres.search import SearchVector
from django.core.exceptions import FieldError
from django.core.cache import cache
from django.db import transaction
from django.db.models import Q
from django.http import Http404, HttpResponse
from django.shortcuts import redirect
from django.utils import timezone
from django_q.tasks import async_task, result as async_result
from django_q.models import OrmQ
from drf_spectacular.utils import (
    extend_schema_view,
    extend_schema,
    inline_serializer,
    OpenApiParameter,
)
from drf_spectacular.types import OpenApiTypes
from private_storage.views import PrivateStorageDetailView
from rest_framework import viewsets, filters, status
from rest_framework.decorators import action
from rest_framework.parsers import MultiPartParser
from rest_framework.permissions import IsAdminUser, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.viewsets import ReadOnlyModelViewSet
from rest_framework_extensions.mixins import NestedViewSetMixin

from projects.exporting.document import render_template
from projects.exporting.report import render_report_to_response
from projects.helpers import DOCUMENT_CONTENT_TYPES, get_file_type, TRUE
from projects.importing import AttributeImporter, AttributeUpdater
from projects.models import (
    FieldComment,
    ProjectComment,
    ProjectDeadline,
    LastReadTimestamp,
    Project,
    ProjectCardSectionAttribute,
    ProjectPhase,
    CommonProjectPhase,
    ProjectType,
    ProjectSubtype,
    ProjectAttributeFile,
    DocumentTemplate,
    Attribute,
    Report,
    Deadline,
    DocumentLinkSection,
    OverviewFilter,
    OverviewFilterAttribute,
)
from projects.models.utils import create_identifier
from projects.permissions.comments import CommentPermissions
from projects.permissions.documents import DocumentPermissions
from projects.permissions.media_file_permissions import (
    has_project_attribute_file_permissions,
)
from projects.permissions.projects import ProjectPermissions
from projects.serializers.comment import (
    CommentSerializer,
    FieldCommentSerializer,
    LastReadTimestampSerializer,
)
from projects.serializers.document import DocumentTemplateSerializer
from projects.serializers.project import (
    ProjectSerializer,
    ProjectSnapshotSerializer,
    ProjectListSerializer,
    ProjectOverviewSerializer,
    ProjectOnMapOverviewSerializer,
    ProjectSubtypeOverviewSerializer,
    AdminProjectSerializer,
    ProjectPhaseSerializer,
    ProjectFileSerializer,
    ProjectExternalDocumentSectionSerializer,
    OverviewFilterSerializer,
    SimpleProjectSerializer,
)
from projects.serializers.projectschema import (
    SimpleAttributeSerializer,
    AdminProjectTypeSchemaSerializer,
    CreateProjectTypeSchemaSerializer,
    EditProjectTypeSchemaSerializer,
    BrowseProjectTypeSchemaSerializer,
    AdminOwnerProjectTypeSchemaSerializer,
    CreateOwnerProjectTypeSchemaSerializer,
    EditOwnerProjectTypeSchemaSerializer,
    ProjectCardSchemaSerializer,
)
from projects.serializers.projecttype import (
    ProjectTypeSerializer,
    ProjectSubtypeSerializer,
)
from projects.serializers.report import ReportSerializer
from projects.serializers.deadline import DeadlineSerializer
from sitecontent.models import ListViewAttributeColumn

log = logging.getLogger(__name__)


class PrivateDownloadViewSetMixin:
    def get(self, request, *args, **kwargs):
        if self.slug_url_kwarg and self.url_path_postfix:
            self.kwargs[
                self.slug_url_kwarg
            ] = f"{self.url_path_postfix}/{self.kwargs.get(self.slug_url_kwarg)}"

        return super().get(request, *args, **kwargs)

    def serve_file(self, private_file):
        response = super().serve_file(private_file)

        # Add CORS headers to allow downloads from any origin
        response["Access-Control-Expose-Headers"] = "content-disposition"
        response["Access-Control-Allow-Origin"] = "*"
        return response


class ProjectTypeViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = ProjectType.objects.all()
    serializer_class = ProjectTypeSerializer


@extend_schema_view(
    retrieve=extend_schema(
        responses={
            200: ProjectSerializer,
            401: OpenApiTypes.STR,
            404: OpenApiTypes.STR,
        },
    ),
    create=extend_schema(
        request=ProjectSerializer,
        responses={
            200: ProjectSerializer,
            400: OpenApiTypes.STR,
            401: OpenApiTypes.STR,
        },
    ),
    update=extend_schema(
        request=ProjectSerializer,
        responses={
            200: ProjectSerializer,
            400: OpenApiTypes.STR,
            401: OpenApiTypes.STR,
        },
    ),
    partial_update=extend_schema(
        request=ProjectSerializer,
        responses={
            200: ProjectSerializer,
            400: OpenApiTypes.STR,
            401: OpenApiTypes.STR,
        },
    ),
)
class ProjectViewSet(NestedViewSetMixin, viewsets.ModelViewSet):
    queryset = Project.objects.all() \
            .select_related("user", "subtype", "subtype__project_type", "phase") \
            .prefetch_related("deadlines", "target_actions")
    permission_classes = [IsAuthenticated, ProjectPermissions]
    filter_backends = (filters.OrderingFilter,)
    try:
        ordering_fields = [
            "name", "pino_number", "created_at", "modified_at",
            "user__first_name", "user__last_name", "user__ad_id",
        ] + [
            f"attribute_data__{attribute.identifier}"
            for attribute in Attribute.objects.filter(searchable=True)
        ]
    except Exception:
        ordering_fields = []


    def get_serializer_class(self):
        if self.action == "list":
            return ProjectListSerializer

        if self.request.query_params.get("snapshot"):
            return ProjectSnapshotSerializer

        user = self.request.user

        if user.has_privilege('admin'):
            return AdminProjectSerializer

        return ProjectSerializer

    def get_queryset(self):
        user = self.request.user
        queryset = self.queryset
        if self.request.method in ['PUT', 'PATCH']:
            queryset = queryset \
                .prefetch_related(
                    'deadlines',
                    'deadlines__deadline',
                    'deadlines__project',
                    'deadlines__deadline__condition_attributes',
                    'deadlines__deadline__initial_calculations',
                    'deadlines__deadline__update_calculations',
                )

        includeds_users = self.request.query_params.get("includes_users", None)
        search = self.request.query_params.get("search", None)
        users = self.request.query_params.get("users", None)
        if includeds_users is not None:
            queryset = self._filter_included_users(includeds_users, queryset)
        if users is not None:
            queryset = self._filter_users(users, queryset)
        if search is not None:
            queryset = self._search(search, queryset)

        queryset = self._filter_private(queryset, user)

        if self.action == "list":
            status = self.request.query_params.get("status")

            if status == "active":
                queryset = queryset.exclude(onhold=True).exclude(archived=True)
            elif status == "onhold":
                queryset = queryset.filter(onhold=True)
            elif status == "archived":
                queryset = queryset.filter(archived=True)

        return queryset

    def _string_filter_to_list(self, filter_string):
        return [_filter.strip().lower() for _filter in filter_string.split(",")]

    def _filter_included_users(self, users, queryset):
        """
        Filter on all user attributes

        Note: Make sure not to validate the queryset
        at any time as that will result in really long
        query time.

        TODO: Support multiple choice fields for
              users. At the time of implementation
              no such fields existed.
        """
        user_queryset = self._filter_users(users, queryset)
        users_list = self._string_filter_to_list(users)
        user_attributes = Attribute.objects.filter(
            value_type__in=[Attribute.TYPE_USER, Attribute.TYPE_PERSONNEL]
        )

        attribute_data_users = self.queryset.none()
        for attribute in user_attributes:
            if attribute.fieldsets.exists():
                parent_attr = attribute.fieldsets.last()
                attribute_filter = {
                    f"attribute_data__{parent_attr.identifier}__contains": [{f"{attribute.identifier}": users_list[0]}]
                }
            else:
                attribute_filter = {
                    f"attribute_data__{attribute.identifier}__in": users_list
                }
            attribute_data_users = attribute_data_users | queryset.filter(
                **attribute_filter
            )

        return attribute_data_users | user_queryset

    def _filter_users(self, users, queryset):
        users_list = self._string_filter_to_list(users)
        return queryset.filter(user__uuid__in=users_list)

    def _search(self, search, queryset):
        # def search_field_for_attribute(attr):
        #     if attr.static_property:
        #         return attr.static_property
        #     elif not attr.fieldset_attribute_target.count():
        #         return f"attribute_data__{attr.identifier}"
        #     else:
        #         fieldset_path = [attr.identifier]
        #         while attr.fieldset_attribute_target.count():
        #             attr = attr.fieldset_attribute_target.get().attribute_source
        #             fieldset_path.append(attr.identifier)
        #
        #         fieldset_path.reverse()
        #         field_string = "__".join(fieldset_path)
        #         return f"attribute_data__{field_string}"

        # search_fields = [
        #     search_field_for_attribute(attr)
        #     for attr in Attribute.objects.filter(searchable=True)
        # ] + ['subtype__project_type__name', 'user__ad_id']
        # return queryset \
        #     .annotate(search=SearchVector(*search_fields)) \
        #     .filter(Q(search__icontains=search) | Q(search=search))

        # Add 'like' condition for partial matching of single lexeme even
        # it prevents bitmap heap scan of gin index. This might be removed
        # if it cerates performance issues in the future
        combined_queryset = queryset.filter(Q(vector_column__icontains=search))
        # Django creates plainto_tsquery() whereas we want to use to_tsquery(),
        # so we'll create our own query to allow prefix matching
        terms = search.split()
        tsquery = " & ".join(terms)
        tsquery += ":*"
        combined_queryset |= queryset.extra(where=["vector_column @@ to_tsquery(%s)"], params=[tsquery])

        # log.info(combined_queryset.query)
        return combined_queryset

    @staticmethod
    def _filter_private(queryset, user):
        if user.has_privilege("admin"):
            return queryset

        return queryset.exclude(~Q(user=user) & Q(public=False))

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["action"] = self.action

        if self.action == "list":
            context["project_schedule_cache"] = \
                cache.get("serialized_project_schedules", {})
            context["listview_attribute_columns"] = ListViewAttributeColumn.objects.all().select_related("attribute")

        return context

    @extend_schema(
        responses={
            200: SimpleProjectSerializer,
            400: OpenApiTypes.STR,
            401: OpenApiTypes.STR,
        },
    )
    @action(
        methods=["get"],
        detail=True,
        permission_classes=[IsAuthenticated, ProjectPermissions],
    )
    def simple(self, request, pk):
        return Response(SimpleProjectSerializer(self.get_object()).data)

    @extend_schema(
        request=ProjectFileSerializer,
        responses={
            200: ProjectFileSerializer,
            400: OpenApiTypes.STR,
            401: OpenApiTypes.STR,
        },
    )
    @action(
        methods=["put"],
        detail=True,
        parser_classes=[MultiPartParser],
        permission_classes=[IsAuthenticated, ProjectPermissions],
    )
    def files(self, request, pk=None):
        project = self.get_object()

        # Query dicts are not mutable by default, temporarily change that
        request.data._mutable = True
        request.data["project"] = project.pk
        request.data._mutable = False

        context = self.get_serializer_context()
        serializer = ProjectFileSerializer(data=request.data, context=context)
        serializer.is_valid(raise_exception=True)

        serializer.save()

        return Response(serializer.data)

    @extend_schema(
        responses=inline_serializer('ExternalDocuments', fields={'sections': ProjectExternalDocumentSectionSerializer(many=True)}),
    )
    @action(
        methods=["get"],
        detail=True,
        permission_classes=[IsAuthenticated, ProjectPermissions],
    )
    def external_documents(self, request, pk):
        project = self.get_object()
        return Response({"sections": [
            ProjectExternalDocumentSectionSerializer(
                project, context={"section": document_section}
            ).data
            for document_section in DocumentLinkSection.objects.all().prefetch_related(
                "documentlinkfieldset_set", "documentlinkfieldset_set__fieldset_attribute",
                "documentlinkfieldset_set__document_link_attribute"
            )
        ]})

    def _get_valid_filters(self, filters_view):
        try:
            attrs = OverviewFilterAttribute.objects.filter(
                **{filters_view: True},
            ).prefetch_related("overview_filter")
        except FieldError:
            return None

        filters = {}

        for attr in attrs:
            try:
                filters[attr.overview_filter].append(attr)
            except KeyError:
                filters[attr.overview_filter] = [attr]

        return filters

    def _get_query(self, filters, prefix=""):
        if prefix:
            prefix = f"{prefix}__"

        params = self.request.query_params
        query = Q()

        for filter_obj, attrs in filters.items():
            try:
                split_params = params.get(filter_obj.identifier).split(",")
            except AttributeError:
                continue

            def get_query_for_filter(param):
                q = Q()

                for attr in attrs:
                    # Only supports one-fieldset-deep queries for now
                    attr = attr.attribute

                    # Manipulate search parameter
                    if attr.value_type == Attribute.TYPE_BOOLEAN:
                        param_parsed = \
                            False if param in ["false", "False"] else bool(param)
                    elif attr.value_type == Attribute.TYPE_DATE:
                        try:
                            param_parsed = \
                                datetime.strptime(param, "%Y-%m-%d").date()
                        except (TypeError, ValueError):
                            # Custom handling if only year is provided, doesn't support fieldsets
                            if not attr.fieldsets.count():
                                try:
                                    year = int(param)
                                    gte_date = datetime(year=year, month=1, day=1).date()
                                    lt_date = datetime(year=year+1, month=1, day=1).date()
                                    if attr.static_property:
                                        q_gte = Q(**{f"{prefix}{attr.static_property}__gte": gte_date})
                                        q_lt = Q(**{f"{prefix}{attr.static_property}__lt": lt_date})
                                        q |= Q(q_gte & q_lt)
                                    else:
                                        q_gte = Q(**{f"{prefix}attribute_data__{attr.identifier}__gte": gte_date})
                                        q_lt = Q(**{f"{prefix}attribute_data__{attr.identifier}__lt": lt_date})
                                        q |= Q(q_gte & q_lt)

                                except (TypeError, ValueError):
                                    pass

                            continue

                    elif attr.value_type == Attribute.TYPE_INTEGER:
                        try:
                            param_parsed = int(param)
                        except (TypeError, ValueError):
                            continue
                    elif attr.value_type == Attribute.TYPE_CHOICE:
                        choices = {}
                        for choice in attr.value_choices.all():
                            choices[choice.identifier] = [choice.value, choice.identifier]
                        param_parsed = choices.get(param)
                    else:
                        param_parsed = param

                    # Handle search criteria special cases
                    if attr.value_type == Attribute.TYPE_USER:
                        postfix = "__ad_id"
                    else:
                        postfix = ""

                    if type(param_parsed) is not list:
                        param_parsed = [param_parsed]

                    for pp in param_parsed:
                        # Add to query
                        if attr.fieldsets.first():
                            q |= Q(**{
                                f"{prefix}attribute_data__{attr.fieldsets.first().identifier}{postfix}__contains": \
                                    [{attr.identifier: pp}]
                            })
                        elif attr.static_property:
                            q |= Q(**{f"{prefix}{attr.static_property}{postfix}": pp})
                        else:
                            # TODO: __iexact is no longer needed if kaavaprosessin_kokoluokka
                            # ever gets refactored
                            q |= Q(**{f"{prefix}attribute_data__{attr.identifier}{postfix}__iexact": pp})

                return q

            param_queries = Q()


            for param in split_params:
                param_queries |= get_query_for_filter(param)

            query &= param_queries

        return query

    @extend_schema(
        responses=OverviewFilterSerializer(many=True),
    )
    @action(
        methods=["get"],
        detail=False,
        permission_classes=[IsAuthenticated, ProjectPermissions],
        url_path="overview/filters",
        url_name="projects-overview-filters",
    )
    def overview_filters(self, request):
        queryset = OverviewFilter.objects.all().prefetch_related("attributes")
        return Response(OverviewFilterSerializer(queryset, many=True).data)

    def _parse_date_range(
        self, start_date_str, end_date_str, today=datetime.now().date()
    ):
        try:
            start_date = datetime.strptime(start_date_str, "%Y-%m-%d").date()
        except (TypeError, ValueError):
            start_date = datetime(today.year, 1, 1).date()

        try:
            end_date = datetime.strptime(end_date_str, "%Y-%m-%d").date()
        except (TypeError, ValueError):
            end_date = datetime(start_date.year, 12, 31).date()

        # Can't go backwards in time
        if start_date > end_date:
            [start_date, end_date] = [start_date, end_date]

        return (start_date, end_date)

    @extend_schema(
        parameters=[
          OpenApiParameter("start_date", OpenApiTypes.DATE, OpenApiParameter.QUERY),
          OpenApiParameter("end_date", OpenApiTypes.DATE, OpenApiParameter.QUERY),
        ],
    )
    @action(
        methods=["get"],
        detail=False,
        permission_classes=[IsAuthenticated, ProjectPermissions],
        url_path="overview/floor_area",
        url_name="projects-overview-floor-area"
    )
    def overview_floor_area(self, request):
        today = datetime.now().date()
        start_date = self.request.query_params.get("start_date")
        end_date = self.request.query_params.get("end_date")
        valid_filters = self._get_valid_filters("filters_floor_area")
        deadline_query = self._get_query(valid_filters, "project")
        project_query = self._get_query(valid_filters)

        start_date, end_date = self._parse_date_range(
            start_date,
            end_date,
            today=today,
        )

        if (end_date-start_date).days > 366:
            return Response(
                {"detail": "Date range has to be 366 days or less"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Dates should be Tuesdays
        start_date += timedelta((1-start_date.weekday()) % 7)
        if end_date.weekday != 1:
            end_date += timedelta(((1-end_date.weekday()) % 7) - 7)

        date_range = [
            start_date + timedelta(days=i)
            for i in range(0, (end_date-start_date+timedelta(days=1)).days, 7)
        ]

        # TODO hard-coded for now; consider a new field for Attribute
        floor_area_attrs = [
            "kerrosalan_lisays_yhteensa_asuminen",
            "kerrosalan_lisays_yhteensa_julkinen",
            "kerrosalan_lisays_yhteensa_muut",
            "kerrosalan_lisays_yhteensa_toimitila",
        ]
        meeting_attrs = [
            "milloin_tarkistettu_ehdotus_lautakunnassa",
            "milloin_tarkistettu_ehdotus_lautakunnassa_2",
            "milloin_tarkistettu_ehdotus_lautakunnassa_3",
            "milloin_tarkistettu_ehdotus_lautakunnassa_4",
        ]

        # TODO add field to mark a Deadline as a "lautakunta" event and filter by that instead
        project_deadlines = ProjectDeadline.objects.filter(
                deadline_query,
                project__public=True,
                deadline__attribute__identifier__in=meeting_attrs + [
                    "milloin_kaavaehdotus_lautakunnassa",
                    "milloin_kaavaehdotus_lautakunnassa_2",
                    "milloin_kaavaehdotus_lautakunnassa_3",
                    "milloin_kaavaehdotus_lautakunnassa_4",
                ]
            ).prefetch_related("project", "project__user",
                               "project__subtype", "project__subtype__project_type",
                               "project__phase", "project__phase__common_project_phase").\
            order_by("project__pk").distinct("project__pk")
        projects_by_date = {
            date: [dl.project for dl in filter(lambda dl: dl.date == date, project_deadlines)]
            for date in date_range
        }

        project_deadlines = ProjectDeadline.objects.filter(
                deadline_query,
                project__public=True,
                deadline__attribute__identifier__in=meeting_attrs,
                date__gte=start_date,
            ).prefetch_related("project").order_by("project__pk").distinct("project__pk")
        projects_in_range_by_date = {
            date: [dl.project for dl in filter(lambda dl: dl.date <= date, project_deadlines)]
            for date in date_range
        }
        projects_in_range = projects_in_range_by_date[end_date]

        confirmed_projects_by_date = {
            date: Project.objects.filter(
                project_query, (
                    Q(attribute_data__tarkistettu_ehdotus_hyvaksytty_kylk__lte=date) |
                    Q(attribute_data__toteutunut_kirje_kaupunginhallitukselle__lte=date) |
                    Q(attribute_data__hyvaksymispaatos_pvm__lte=date)
                ),
                public=True,
                pk__in=[p.pk for p in projects_in_range],
            ).order_by("pk")
            for date in date_range
        }

        def get_floor_area(date, attr):
            if date < today:
                projects = confirmed_projects_by_date[date]
            else:
                projects = projects_in_range_by_date[date]

            total = 0

            for project in projects:
                total += int(float(project.attribute_data.get(attr, 0)))

            return total

        floor_area_by_date = {
            start_date: {
                attr: get_floor_area(start_date, attr)
                for attr in floor_area_attrs
            }
        }

        floor_area_by_date[start_date]["total"] = \
            sum(floor_area_by_date[start_date].values())

        for date, prev in zip(date_range[1:], date_range[:-1]):
            if date < today:
                new_projects = set(confirmed_projects_by_date[date]) - \
                    set(confirmed_projects_by_date[prev])
            else:
                new_projects = set(projects_in_range_by_date[date]) - \
                    set(projects_in_range_by_date[prev])

            floor_area_by_date[date] = {}

            for attr in floor_area_attrs:
                total = floor_area_by_date[prev][attr]

                for project in new_projects:
                    total += int(float( \
                        project.attribute_data.get(attr, 0)))

                floor_area_by_date[date][attr] = total

            floor_area_by_date[date]["total"] = \
                sum(floor_area_by_date[date].values())

        total_predicted = sum(floor_area_by_date[date_range[-1]].values())

        latest_tuesday = \
            today - timedelta((today.weekday() - 1) % 7)

        try:
            total_to_date = sum(floor_area_by_date[latest_tuesday].values())
        except KeyError:
            if latest_tuesday > end_date:
                total_to_date = total_predicted
            else:
                total_to_date = 0

        return Response({
            "date": today,
            "total_to_date": total_to_date,
            "total_predicted": total_predicted,
            "daily_stats": [
                {
                    "date": str(date),
                    "meetings": len(projects_by_date[date]),
                    "projects": [
                        ProjectOverviewSerializer(project).data
                        for project in projects_by_date[date]
                    ],
                    "floor_area": {
                        "is_prediction": date >= today,
                        **floor_area_by_date[date],
                    },
                }
                for date in date_range
            ]
        })

    @extend_schema(
        parameters=[
          OpenApiParameter("start_date", OpenApiTypes.DATE, OpenApiParameter.QUERY),
          OpenApiParameter("end_date", OpenApiTypes.DATE, OpenApiParameter.QUERY),
        ],
    )
    @action(
        methods=["get"],
        detail=False,
        permission_classes=[IsAuthenticated, ProjectPermissions],
        url_path="overview/by_subtype",
        url_name="projects-overview-by-subtype"
    )
    def overview_by_subtype(self, request):
        valid_filters = self._get_valid_filters("filters_by_subtype")
        start_date = self.request.query_params.get("start_date")
        end_date = self.request.query_params.get("end_date")
        query = self._get_query(valid_filters)
        queryset = ProjectSubtype.objects.all().prefetch_related("phases")

        # TODO hard-coded for now; consider a new field for Attribute
        date_range_attrs = [
            "toteutunut_kirje_kaupunginhallitukselle",
            "tarkistettu_ehdotus_hyvaksytty_kylk",
            "milloin_tarkistettu_ehdotus_lautakunnassa",
            "milloin_tarkistettu_ehdotus_lautakunnassa_2",
            "milloin_tarkistettu_ehdotus_lautakunnassa_3",
            "milloin_tarkistettu_ehdotus_lautakunnassa_4",
        ]

        if start_date or end_date:
            start_date, end_date = self._parse_date_range(start_date, end_date)
            print(start_date, end_date)
            start_query = Q()
            end_query = Q()
            for attr in date_range_attrs:
                start_query |= Q(**{f"attribute_data__{attr}__gte": start_date})
                end_query |= Q(**{f"attribute_data__{attr}__lte": end_date})
            query &= start_query & end_query

        return Response({
            "subtypes": ProjectSubtypeOverviewSerializer(
                queryset, many=True, context={"query": query},
            ).data
        })

    @extend_schema(
        responses={
            200: ProjectOnMapOverviewSerializer(many=True),
            400: OpenApiTypes.STR,
            401: OpenApiTypes.STR,
        },
    )
    @action(
        methods=["get"],
        detail=False,
        permission_classes=[IsAuthenticated, ProjectPermissions],
        url_path="overview/on_map",
        url_name="projects-overview-on-map"
    )
    def overview_on_map(self, request):
        valid_filters = self._get_valid_filters("filters_on_map")
        query = self._get_query(valid_filters)
        queryset = Project.objects.filter(query, public=True)\
            .prefetch_related("phase", "phase__common_project_phase", "phase__project_subtype",
                              "subtype", "subtype__project_type",
                              "user",
                              )
        return Response({
            "projects": ProjectOnMapOverviewSerializer(
                queryset, many=True, context={"query": query},
            ).data
        })


class ProjectPhaseViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = ProjectPhase.objects.all().prefetch_related("common_project_phase", "project_subtype", "project_subtype__project_type")
    serializer_class = ProjectPhaseSerializer


class ProjectCardSchemaViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = ProjectCardSectionAttribute.objects.all()\
        .select_related("attribute", "section").prefetch_related("attribute__value_choices")\
        .order_by("section__index", "index")
    serializer_class = ProjectCardSchemaSerializer


class AttributeViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Attribute.objects.all()
    serializer_class = SimpleAttributeSerializer


@extend_schema(
    parameters=[
      OpenApiParameter("owner", OpenApiTypes.BOOL, OpenApiParameter.QUERY),
      OpenApiParameter("project", OpenApiTypes.INT, OpenApiParameter.QUERY),
    ],
)
class ProjectTypeSchemaViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = ProjectType.objects.all()

    def get_serializer_class(self):
        user = self.request.user

        owner = self.request.query_params.get("owner")
        project = self.request.query_params.get("project")

        try:
            project = Project.objects.get(pk=int(project))
        except Exception:
            project = None

        is_owner = \
            owner in ["1", "true", "True"] or \
            project and project.user == user

        if is_owner:
            return {
                "admin": AdminOwnerProjectTypeSchemaSerializer,
                "create": CreateOwnerProjectTypeSchemaSerializer,
                "edit": EditOwnerProjectTypeSchemaSerializer,
            }[user.privilege]
        else:
            return {
                "admin": AdminProjectTypeSchemaSerializer,
                "create": CreateProjectTypeSchemaSerializer,
                "edit": EditProjectTypeSchemaSerializer,
                "browse": BrowseProjectTypeSchemaSerializer,
            }[user.privilege]


class ProjectSubtypeViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = ProjectSubtype.objects.all()
    serializer_class = ProjectSubtypeSerializer


class ProjectAttributeFileDownloadView(
    PrivateDownloadViewSetMixin, PrivateStorageDetailView
):
    model = ProjectAttributeFile
    slug_field = "file"
    slug_url_kwarg = "path"
    url_path_postfix = "projects"

    def get_queryset(self):
        # Queryset that is allowed to be downloaded
        return ProjectAttributeFile.objects.all()

    def can_access_file(self, private_file):
        # NOTE: This overrides PRIVATE_STORAGE_AUTH_FUNCTION
        # TODO: Change permission function when user permissions has been implemented
        return has_project_attribute_file_permissions(private_file, self.request)


class FieldCommentViewSet(NestedViewSetMixin, viewsets.ModelViewSet):
    queryset = FieldComment.objects.all().select_related("user").prefetch_related("fieldset_path_locations")
    serializer_class = FieldCommentSerializer
    permission_classes = [IsAuthenticated, CommentPermissions]
    filter_backends = (filters.OrderingFilter,)
    ordering_fields = ("created_at", "modified_at")

    def initial(self, request, *args, **kwargs):
        super(FieldCommentViewSet, self).initial(request, *args, **kwargs)
        self.parent_instance = self.get_parent_instance()

    def get_parent_instance(self):
        qd = self.get_parents_query_dict()
        project_id = qd.get("project")
        project = Project.objects.filter(pk=project_id).first()

        if not project:
            raise Http404
        return project

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["parent_instance"] = self.get_parent_instance()
        return context

    @action(methods=["get"], detail=False, url_path=r"field/(?P<field_identifier>\w+)", url_name="project-field-comments")
    def field_comments(self, request, *args, **kwargs):
        identifier = kwargs.get("field_identifier", "")
        comments = FieldComment.objects \
            .filter(field__identifier=identifier) \
            .select_related("user")
        page = self.paginate_queryset(comments)

        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(comments, many=True)
        return Response(serializer.data)


class CommentViewSet(NestedViewSetMixin, viewsets.ModelViewSet):
    queryset = ProjectComment.objects.all().select_related("user")
    serializer_class = CommentSerializer
    permission_classes = [IsAuthenticated, CommentPermissions]
    filter_backends = (filters.OrderingFilter,)
    ordering_fields = ("created_at", "modified_at")

    def initial(self, request, *args, **kwargs):
        super(CommentViewSet, self).initial(request, *args, **kwargs)
        self.parent_instance = self.get_parent_instance()

    def get_parent_instance(self):
        qd = self.get_parents_query_dict()
        project_id = qd.get("project")
        project = Project.objects.filter(pk=project_id).first()

        if not project:
            raise Http404
        return project

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["parent_instance"] = self.parent_instance
        return context

    @action(methods=["get"], detail=False)
    def unread(self, request, *args, **kwargs):
        try:
            timestamp = LastReadTimestamp.objects.get(
                project=self.parent_instance, user=request.user
            ).timestamp
        except LastReadTimestamp.DoesNotExist:
            timestamp = datetime.now(pytz.utc)

        unread = ProjectComment.objects \
            .filter(created_at__gt=timestamp, project=self.parent_instance) \
            .select_related("user")
        page = self.paginate_queryset(unread)

        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(unread, many=True)
        return Response(serializer.data)

    @action(methods=["post"], detail=False)
    def mark_as_read(self, request, *args, **kwargs):
        serializer = LastReadTimestampSerializer(data=request.data, many=False)
        if serializer.is_valid():
            timestamp, _ = LastReadTimestamp.objects.update_or_create(
                project=self.parent_instance,
                user=request.user,
                defaults={"timestamp": serializer.data["timestamp"]}
            )
            return Response(serializer.data)

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class DocumentViewSet(ReadOnlyModelViewSet):
    queryset = DocumentTemplate.objects.all()
    permission_classes = [IsAuthenticated, DocumentPermissions]
    lookup_field = "slug"
    serializer_class = DocumentTemplateSerializer

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        self.project = self.get_project()

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["project"] = self.project
        return context

    def get_queryset(self):
        phases = CommonProjectPhase.objects.filter(
            phases__project_subtype=self.project.subtype,
        )
        return DocumentTemplate.objects.filter(
            common_project_phases__in=phases,
        ).distinct()

    def get_project(self):
        project_id = self.kwargs.get("project_pk")
        project = Project.objects.filter(pk=project_id).first()

        if not project:
            raise Http404
        return project

    def _set_response_headers(self, response, filename, document_type):
        response["Content-Disposition"] = "attachment; filename={}.{}".format(
            filename, document_type
        )
        # Since we are not using DRFs response here, we set a custom CORS control header
        response["Access-Control-Expose-Headers"] = "content-disposition"
        response["Access-Control-Allow-Origin"] = "*"

    @extend_schema(
        parameters=[
          OpenApiParameter("task", OpenApiTypes.STR, OpenApiParameter.QUERY),
          OpenApiParameter("filename", OpenApiTypes.STR, OpenApiParameter.QUERY),
          OpenApiParameter("preview", OpenApiTypes.BOOL, OpenApiParameter.QUERY),
        ],
    )
    def retrieve(self, request, *args, **kwargs):
        task_id = request.query_params.get("task")
        filename = request.query_params.get("filename")
        document_template = self.get_object()

        if filename is None:
            filename = "{}-{}-{}".format(
                create_identifier(self.project.name),
                document_template.name,
                timezone.now().date(),
            )

        doc_type = get_file_type(document_template.file.path)

        preview = \
            True if request.query_params.get("preview") in TRUE \
            else False

        immediate =  \
            True if request.query_params.get("immediate") in TRUE \
            else False

        if immediate:
            document = render_template(self.project, document_template, preview)
            response = HttpResponse(
                document,
                content_type=DOCUMENT_CONTENT_TYPES[doc_type],
            )
            self._set_response_headers(response, filename, doc_type)
            return response

        if task_id:
            result = async_result(task_id)
            if result:
                response = HttpResponse(
                    result,
                    content_type=DOCUMENT_CONTENT_TYPES[doc_type],
                )
                self._set_response_headers(response, filename, doc_type)
                return response

            queued_ids = [
                ormq.task_id() for ormq in OrmQ.objects.all()
            ]
            if task_id in queued_ids:
                return Response(
                    {"detail": task_id},
                    status=status.HTTP_202_ACCEPTED,
                )
            else:
                return Response(
                    {"detail": "Requested task not found"},
                    status=status.HTTP_404_NOT_FOUND,
                )

        document_task = async_task(
            render_template,
            self.project, document_template, preview,
        )

        return Response(
            {"detail": document_task},
            status=status.HTTP_202_ACCEPTED,
        )

    @extend_schema(
        responses={
            200: DocumentTemplateSerializer(many=True),
            400: OpenApiTypes.STR,
            401: OpenApiTypes.STR,
        },
    )
    def list(self, request, *args, **kwargs):
        qs = self.get_queryset().filter(project_card_default_template=False)
        return Response(
            self.get_serializer(qs, many=True).data,
            status=status.HTTP_200_OK
        )


class DocumentTemplateDownloadView(
    PrivateDownloadViewSetMixin, PrivateStorageDetailView
):
    model = DocumentTemplate
    slug_field = "file"
    slug_url_kwarg = "path"
    url_path_postfix = "document_templates"

    def get_queryset(self):
        # Queryset that is allowed to be downloaded
        return self.model.objects.all()

    def can_access_file(self, private_file):
        return self.request.user.has_privilege("admin")

@action(
    methods=["post"],
    detail=True,
    permission_classes=[IsAuthenticated, ProjectPermissions],
)
class UploadSpecifications(APIView):
    parser_classes = (MultiPartParser,)
    permission_classes = [IsAuthenticated, IsAdminUser]

    def post(self, request, format=None):
        if request.FILES and request.FILES["specifications"]:
            specifications_file = request.FILES["specifications"]

            options = {"filename": specifications_file}
            attribute_importer = AttributeImporter(options)
            attribute_importer.run()

        return redirect(".")


@action(
    methods=["post"],
    detail=True,
    permission_classes=[IsAuthenticated, ProjectPermissions],
)
class UploadAttributeUpdate(APIView):
    parser_classes = (MultiPartParser,)
    permission_classes = [IsAuthenticated, IsAdminUser]

    def post(self, request, format=None):
        if request.FILES and request.FILES["specifications"]:
            specifications_file = request.FILES["specifications"]

            options = {"filename": specifications_file}
            attribute_importer = AttributeUpdater(options)
            attribute_importer.run()

        return redirect(".")


def admin_attribute_updater_template(request):
    response = HttpResponse(
        content_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="muuttuneet-tunnisteet-template.csv"'},
    )

    writer = csv.writer(response)
    writer.writerow(["Korvattava tunniste", "Korvaava tunniste"])
    writer.writerow(["vanha_tunniste", "uusi_tunniste"])

    return response


class ReportViewSet(ReadOnlyModelViewSet):
    queryset = Report.objects.filter(hidden=False)
    serializer_class = ReportSerializer

    def get_queryset(self):
        user = self.request.user
        queryset = self.queryset

        if not user.has_privilege('admin'):
            queryset = queryset.exclude(is_admin_report=True)

        return queryset

    def get_project_queryset(self, report):
        params = self.request.query_params
        filters = report.filters.filter(
            identifier__in=params.keys()
        )
        projects = Project.objects.filter(onhold=False, public=True)
        for report_filter in filters:
            projects = report_filter.filter_projects(
                params.get(report_filter.identifier),
                queryset=projects,
            )
        return projects

    def _remove_from_queue(self, *args, **kwargs):
        pass


    def retrieve(self, request, *args, **kwargs):
        task_id = request.query_params.get("task")

        if task_id:
            result = async_result(task_id)
            if result:
                return result

            queued_ids = [
                ormq.task_id() for ormq in OrmQ.objects.all()
            ]
            if task_id in queued_ids:
                return Response(
                    {"detail": task_id},
                    status=status.HTTP_202_ACCEPTED,
                )
            else:
                return Response(
                    {"detail": "Requested task not found"},
                    status=status.HTTP_404_NOT_FOUND,
                )

        filename = request.query_params.get("filename")
        report = self.get_object()
        preview = self.request.query_params.get("preview", None) in [
            "True", "true", "1",
        ]
        try:
            limit = int(self.request.query_params.get("limit", None))
        except (ValueError, TypeError):
            limit = None

        project_ids = [
            project.pk for project in self.get_project_queryset(report)
        ]

        if filename is None:
            filename = "{}-{}".format(
                create_identifier(report.name), timezone.now().date()
            )

        if not preview:
            response = HttpResponse(content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            response["Access-Control-Expose-Headers"] = "content-disposition"
            response["Content-Disposition"] = "attachment; filename={}.xlsx".format(filename)
        else:
            response = HttpResponse(content_type="text/csv; header=present; charset=UTF-8")

        # Since we are not using DRFs response here, we set a custom CORS control header
        response["Access-Control-Allow-Origin"] = "*"

        report_task = async_task(
            render_report_to_response,
            report, project_ids, response, preview, limit,
        )

        return Response(
            {"detail": report_task},
            status=status.HTTP_202_ACCEPTED,
        )

    @extend_schema(
        responses={
            200: ReportSerializer,
            400: OpenApiTypes.STR,
            401: OpenApiTypes.STR,
        },
    )
    def list(self, request, *args, **kwargs):
        self.serializer_class = ReportSerializer
        return super().list(request, *args, **kwargs)


class DeadlineSchemaViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = DeadlineSerializer
    queryset = Deadline.objects.all()

    def get_queryset(self):
        try:
            subtype = int(self.request.query_params.get("subtype", None))
        except (ValueError, TypeError):
            subtype = None

        filters = {}

        if subtype:
            filters["phase__project_subtype__id"] = subtype

        return Deadline.objects.filter(**filters)
