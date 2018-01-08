from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import path

import projects.views

admin.autodiscover()


urlpatterns = [
    path('admin/', admin.site.urls),
    path('', projects.views.ProjectListView.as_view(), name='project-list'),
    path('projects/create/', projects.views.ProjectCreateView.as_view(), name='project-create'),
    path('projects/<int:pk>/edit/', projects.views.ProjectUpdateView.as_view(), name='project-edit'),
    path('reports/', projects.views.report_view, name='reports'),
]

if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
