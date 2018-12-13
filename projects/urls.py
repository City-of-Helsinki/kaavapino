from rest_framework import routers
from rest_framework_extensions.routers import ExtendedSimpleRouter

from projects.views import (
    ProjectViewSet,
    ProjectPhaseViewSet,
    ProjectTypeSchemaViewSet,
    ProjectTypeViewSet,
    ProjectSubtypeViewSet,
    CommentViewSet,
    DocumentViewSet,
    ReportViewSet,
)

app_name = "projects"

router = routers.SimpleRouter()
projects_router = ExtendedSimpleRouter()
projects = projects_router.register(r"projects", ProjectViewSet, base_name="projects")
projects.register(
    r"comments",
    CommentViewSet,
    base_name="project-comments",
    parents_query_lookups=["project"],
)

router.registry.extend(projects_router.registry)
router.register(r"projecttypes", ProjectTypeViewSet)
router.register(r"projectsubtypes", ProjectSubtypeViewSet)
router.register(r"phases", ProjectPhaseViewSet)
router.register(r"schemas", ProjectTypeSchemaViewSet)
router.register(r"reports", ReportViewSet)
router.register(r"projects/(?P<project_pk>[^/.]+)/documents", DocumentViewSet)

urlpatterns = router.urls
