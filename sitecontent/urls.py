from rest_framework import routers

from sitecontent.views import FooterSectionViewSet


app_name = "sitecontent"

router = routers.SimpleRouter(trailing_slash=True)

router.register(r"footer", FooterSectionViewSet)

urlpatterns = router.urls
