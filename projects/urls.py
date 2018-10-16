from django.urls import path

from . import views

app_name = "projects"

urlpatterns = [
    path("", views.ProjectListView.as_view(), name="list"),
    path("create/", views.project_edit, name="create"),
    path("<int:pk>/", views.ProjectCardView.as_view(), name="card"),
    path("<int:pk>/edit/", views.project_edit, name="edit"),
    path("<int:pk>/edit/phase/<int:phase_id>", views.project_edit, name="edit-phase"),
    path("<int:pk>/change-phase/", views.project_change_phase, name="change-phase"),
    path(
        "<int:pk>/create-document/",
        views.DocumentCreateView.as_view(),
        name="document-create",
    ),
    path(
        "<int:project_pk>/create-document/<int:document_pk>/",
        views.document_download_view,
        name="document-download",
    ),
]
