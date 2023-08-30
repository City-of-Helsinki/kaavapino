from django.conf import settings
from django.urls import re_path
from django.conf.urls.static import static
from helusers.admin_site import admin
from django.urls import path, include
from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularRedocView,
    SpectacularSwaggerView,
)
from rest_framework import routers

from projects import views as project_views
from projects.urls import router as projects_router
from sitecontent.urls import router as sitecontent_router
from sitecontent.views import Legend, TargetFloorAreas, Ping
from users.views import PersonnelDetail, PersonnelList
from users.urls import router as users_router

admin.autodiscover()

router = routers.DefaultRouter()
router.registry.extend(projects_router.registry)
router.registry.extend(sitecontent_router.registry)
router.registry.extend(users_router.registry)

# Media URL in the settings is usually set to a value that starts with a backslash,
# that should not be included when defining a path url.
MEDIA_URL = (
    settings.MEDIA_URL
    if settings.MEDIA_URL[0] != "/"
    else settings.MEDIA_URL.lstrip("/")
)

urlpatterns = [
    path(
        "admin/upload_specifications",
        project_views.UploadSpecifications.as_view(),
        name="admin_upload_specifications",
    ),
    path(
        "admin/upload_attribute_updater",
        project_views.UploadAttributeUpdate.as_view(),
        name="admin_upload_attribute_updater",
    ),
    path(
        "admin/admin_attribute_updater_template",
        project_views.admin_attribute_updater_template,
        name="admin_attribute_updater_template",
    ),
    path("admin/", admin.site.urls),
    path('pysocial/', include('social_django.urls', namespace='social')),
    path('helauth/', include('helusers.urls')),
    path("v1/legend/", Legend.as_view(), name="legend"),
    path("v1/targetfloorareas/", TargetFloorAreas.as_view(), name="targetfloorareas"),
    path("v1/personnel/", PersonnelList.as_view(), name="personnellist"),
    path("v1/ping/", Ping.as_view(), name="ping"),
    path("v1/", include(router.urls)),
    re_path(
        r"v1/personnel/(?P<pk>.*)$",
        PersonnelDetail.as_view(),
        name="personneldetail"
    ),
    re_path(
        r"{}projects/(?P<path>.*)$".format(MEDIA_URL),
        project_views.ProjectAttributeFileDownloadView.as_view(),
        name="serve_private_project_file",
    ),
    re_path(
        r"{}document_templates/(?P<path>.*)$".format(MEDIA_URL),
        project_views.DocumentTemplateDownloadView.as_view(),
        name="serve_private_document_template_file",
    ),
    # OpenAPI 3 documentation with Swagger UI:
    path('schema/', SpectacularAPIView.as_view(), name='schema'),
    # Optional UI:
    path('schema/swagger-ui/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),
    path('schema/redoc/', SpectacularRedocView.as_view(url_name='schema'), name='redoc'),
]

if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
