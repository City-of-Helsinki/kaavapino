from rest_framework import routers

from sitecontent.views import FooterSectionViewSet


app_name = "sitecontent"

router = routers.SimpleRouter()

router.register(r"footer", FooterSectionViewSet)

urlpatterns = router.urls
