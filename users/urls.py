from rest_framework import routers

from users.views import UserViewSet

app_name = "users"

router = routers.SimpleRouter()

router.register(r"users", UserViewSet)

urlpatterns = router.urls
