from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import path, include
from rest_framework import routers

from projects.urls import router as projects_router
from users.urls import router as users_router

admin.autodiscover()


router = routers.DefaultRouter()
router.registry.extend(projects_router.registry)
router.registry.extend(users_router.registry)

urlpatterns = [
    path("admin/", admin.site.urls),
    path("v1/", include(router.urls)),
    path("accounts/", include("allauth.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
