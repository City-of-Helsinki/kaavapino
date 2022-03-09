from rest_framework import routers
from rest_framework_extensions.routers import ExtendedSimpleRouter

from projects.views import (
    ProjectViewSet,
    ProjectPhaseViewSet,
    AttributeViewSet,
    ProjectTypeSchemaViewSet,
    ProjectCardSchemaViewSet,
    ProjectTypeViewSet,
    ProjectSubtypeViewSet,
    FieldCommentViewSet,
    CommentViewSet,
    DocumentViewSet,
    ReportViewSet,
    DeadlineSchemaViewSet,
)

app_name = "projects"

router = routers.SimpleRouter()
projects_router = ExtendedSimpleRouter()
projects = projects_router.register(r"projects", ProjectViewSet, basename="projects")
projects.register(
    r"comments/fields",
    FieldCommentViewSet,
    basename="project-field-comments",
    parents_query_lookups=["project"],
)
projects.register(
    r"comments",
    CommentViewSet,
    basename="project-comments",
    parents_query_lookups=["project"],
)

router.registry.extend(projects_router.registry)
router.register(r"projecttypes", ProjectTypeViewSet)
router.register(r"projectsubtypes", ProjectSubtypeViewSet)
router.register(r"phases", ProjectPhaseViewSet)
router.register(r"schemas", ProjectTypeSchemaViewSet)
router.register(r"attributes", AttributeViewSet)
router.register(r"cardschema", ProjectCardSchemaViewSet)
router.register(r"reports", ReportViewSet)
router.register(r"projects/(?P<project_pk>[^/.]+)/documents", DocumentViewSet)
router.register(r"deadlines", DeadlineSchemaViewSet)
urlpatterns = router.urls
