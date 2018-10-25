from rest_framework import routers

from projects.views import ProjectViewSet, ProjectPhaseViewSet

app_name = "projects"

router = routers.SimpleRouter()

router.register(r"projects", ProjectViewSet)
router.register(r"phases", ProjectPhaseViewSet)

urlpatterns = router.urls
