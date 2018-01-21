from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import path

import projects.views

admin.autodiscover()


urlpatterns = [
    path('admin/', admin.site.urls),
    path('', projects.views.ProjectListView.as_view(), name='project-list'),
    path('projects/create/', projects.views.project_edit, name='project-create'),
    path('projects/<int:pk>/', projects.views.ProjectCardView.as_view(), name='project-card'),
    path('projects/<int:pk>/edit/', projects.views.project_edit, name='project-edit'),
    path('projects/<int:pk>/create-document/', projects.views.DocumentCreateView.as_view(), name='document-create'),
    path('projects/<int:project_pk>/create-document/<int:document_pk>/',
         projects.views.document_download_view, name='document-download'),
    path('reports/', projects.views.report_view, name='reports'),
]

if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
