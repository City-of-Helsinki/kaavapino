from rest_framework import routers

from users.views import UserViewSet

app_name = "users"

router = routers.SimpleRouter(trailing_slash=True)

router.register(r"users", UserViewSet)

urlpatterns = router.urls
