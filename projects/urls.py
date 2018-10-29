from rest_framework import routers

from projects.views import ProjectViewSet, ProjectPhaseViewSet, ProjectTypeSchemaViewSet

app_name = "projects"

router = routers.SimpleRouter()

router.register(r"projects", ProjectViewSet)
router.register(r"phases", ProjectPhaseViewSet)
router.register(r"schemas", ProjectTypeSchemaViewSet)

urlpatterns = router.urls
