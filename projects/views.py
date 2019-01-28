from django.db import transaction
from django.db.models import Q
from django.http import Http404, HttpResponse
from django.shortcuts import redirect
from django.utils import timezone
from private_storage.views import PrivateStorageDetailView
from rest_framework import viewsets, filters
from rest_framework.decorators import action
from rest_framework.parsers import MultiPartParser
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.viewsets import ReadOnlyModelViewSet
from rest_framework_extensions.mixins import NestedViewSetMixin

from projects.exporting.document import render_template
from projects.exporting.report import render_report_to_response
from projects.filters import ProjectFilter
from projects.importing import AttributeImporter
from projects.importing.report import ReportTypeCreator
from projects.models import (
    ProjectComment,
    Project,
    ProjectPhase,
    ProjectType,
    ProjectSubtype,
    ProjectAttributeFile,
    DocumentTemplate,
    Attribute,
    Report,
)
from projects.models.utils import create_identifier
from projects.permissions.comments import CommentPermissions
from projects.permissions.documents import DocumentPermissions
from projects.permissions.media_file_permissions import (
    has_project_attribute_file_permissions,
)
from projects.serializers.comment import CommentSerializer
from projects.serializers.document import DocumentTemplateSerializer
from projects.serializers.project import (
    ProjectSerializer,
    ProjectPhaseSerializer,
    ProjectFileSerializer,
)
from projects.serializers.projectschema import ProjectTypeSchemaSerializer
from projects.serializers.projecttype import (
    ProjectTypeSerializer,
    ProjectSubtypeSerializer,
)
from projects.serializers.report import ReportSerializer


class PrivateDownloadViewSetMixin:
    def get(self, request, *args, **kwargs):
        if self.slug_url_kwarg and self.url_path_postfix:
            self.kwargs[
                self.slug_url_kwarg
            ] = f"{self.url_path_postfix}/{self.kwargs.get(self.slug_url_kwarg)}"

        return super().get(request, *args, **kwargs)


class ProjectTypeViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = ProjectType.objects.all()
    serializer_class = ProjectTypeSerializer


class ProjectViewSet(NestedViewSetMixin, viewsets.ModelViewSet):
    queryset = Project.objects.all().select_related("user")
    serializer_class = ProjectSerializer
    filter_backends = (filters.OrderingFilter,)
    ordering_fields = ("name", "identifier", "created_at", "modified_at")

    def get_queryset(self):
        user = self.request.user
        queryset = self.queryset

        includeds_users = self.request.query_params.get("includes_users", None)
        users = self.request.query_params.get("users", None)
        if includeds_users is not None:
            queryset = self._filter_included_users(includeds_users, queryset)
        if users is not None:
            queryset = self._filter_users(users, queryset)

        queryset = self._filter_private(queryset, user)
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
        user_attributes = Attribute.objects.filter(value_type=Attribute.TYPE_USER)

        attribute_data_users = self.queryset.none()
        for attribute in user_attributes:
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

    @staticmethod
    def _filter_private(queryset, user):
        if user.is_superuser:
            return queryset

        return queryset.exclude(~Q(user=user) & Q(public=False))

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["action"] = self.action
        return context

    @action(methods=["put"], detail=True, parser_classes=[MultiPartParser])
    def files(self, request, pk=None):
        project = self.get_object()

        # Query dicts are not mutable by default, temporarily change that
        request.data._mutable = True
        request.data["project"] = project.pk
        request.data._mutable = False

        context = self.get_serializer_context()
        serializer = ProjectFileSerializer(data=request.data, context=context)
        serializer.is_valid(raise_exception=True)

        with transaction.atomic():
            # Remove any file using the same attribute for the project
            ProjectAttributeFile.objects.filter(
                attribute=serializer.validated_data["attribute"], project=project
            ).delete()

            # Save the new file and metadata to disk
            serializer.save()

        return Response(serializer.data)


class ProjectPhaseViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = ProjectPhase.objects.all()
    serializer_class = ProjectPhaseSerializer


class ProjectTypeSchemaViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = ProjectType.objects.all()
    serializer_class = ProjectTypeSchemaSerializer


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


class CommentViewSet(NestedViewSetMixin, viewsets.ModelViewSet):
    queryset = ProjectComment.objects.all().select_related("user")
    serializer_class = CommentSerializer
    permission_classes = (CommentPermissions,)
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


class DocumentViewSet(ReadOnlyModelViewSet):
    queryset = DocumentTemplate.objects.all()
    permission_classes = (DocumentPermissions,)
    lookup_field = "slug"

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        self.project = self.get_project()

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["project"] = self.project
        return context

    def get_project(self):
        project_id = self.kwargs.get("project_pk")
        project = Project.objects.filter(pk=project_id).first()

        if not project:
            raise Http404
        return project

    def retrieve(self, request, *args, **kwargs):
        filename = request.query_params.get("filename")
        document_template = self.get_object()

        if filename is None:
            filename = "{}-{}-{}".format(
                create_identifier(self.project.name),
                document_template.name,
                timezone.now().date(),
            )

        output = render_template(self.project, document_template)
        response = HttpResponse(
            output,
            content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
        response["Content-Disposition"] = "attachment; filename={}.docx".format(
            filename
        )

        # Since we are not using DRFs response here, we set a custom CORS control header
        response["Access-Control-Expose-Headers"] = "content-disposition"
        response["Access-Control-Allow-Origin"] = "*"
        return response

    def list(self, request, *args, **kwargs):
        self.serializer_class = DocumentTemplateSerializer
        return super().list(request, *args, **kwargs)


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
        return self.request.user.is_superuser


class UploadSpecifications(APIView):
    parser_classes = (MultiPartParser,)
    permission_classes = (IsAdminUser,)

    def post(self, request, format=None):
        if request.FILES and request.FILES["specifications"]:
            specifications_file = request.FILES["specifications"]

            options = {"filename": specifications_file}
            attribute_importer = AttributeImporter(options)
            attribute_importer.run()

        return redirect(".")


class SetupDefaultReports(APIView):
    parser_classes = (MultiPartParser,)
    permission_classes = (IsAdminUser,)

    def post(self, request, format=None):
        report_type_creator = ReportTypeCreator()
        report_type_creator.run()

        return redirect(".")


class ReportViewSet(ReadOnlyModelViewSet):
    queryset = Report.objects.all()

    def get_queryset(self):
        user = self.request.user
        queryset = self.queryset

        if not user.is_superuser:
            queryset = queryset.exclude(is_admin_report=True)

        return queryset

    def get_project_queryset(self, report):
        pf = ProjectFilter(
            self.request.query_params,
            queryset=Project.objects.filter(
                subtype__project_type=report.project_type, public=True
            ),
            request=self.request,
        )
        return pf.qs

    def retrieve(self, request, *args, **kwargs):
        filename = request.query_params.get("filename")
        report = self.get_object()

        projects = self.get_project_queryset(report)

        if filename is None:
            filename = "{}-{}".format(
                create_identifier(report.name), timezone.now().date()
            )

        response = HttpResponse(content_type="text/csv; header=present; charset=UTF-8")
        response["Content-Disposition"] = "attachment; filename={}.csv".format(filename)

        # Since we are not using DRFs response here, we set a custom CORS control header
        response["Access-Control-Expose-Headers"] = "content-disposition"
        response["Access-Control-Allow-Origin"] = "*"

        return render_report_to_response(report, projects, response)

    def list(self, request, *args, **kwargs):
        self.serializer_class = ReportSerializer
        return super().list(request, *args, **kwargs)
