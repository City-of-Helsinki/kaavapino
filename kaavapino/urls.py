from django.conf import settings
from django.conf.urls import url
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import path, include
from rest_framework import routers

from projects import views as project_views
from projects.urls import router as projects_router
from users.urls import router as users_router

admin.autodiscover()


router = routers.DefaultRouter()
router.registry.extend(projects_router.registry)
router.registry.extend(users_router.registry)

# Media URL in the settings is usually set to a value that starts with a backslash,
# that should not be included when defining a path url.
MEDIA_URL = (
    settings.MEDIA_URL
    if settings.MEDIA_URL[0] is not "/"
    else settings.MEDIA_URL.lstrip("/")
)

urlpatterns = [
    path("admin/", admin.site.urls),
    path("v1/", include(router.urls)),
    path("accounts/", include("allauth.urls")),
    url(
        r"{}projects/(?P<path>.*)$".format(MEDIA_URL),
        project_views.ProjectAttributeFileDownloadView.as_view(),
        name="serve_private_project_file",
    ),
    ),
]

if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
