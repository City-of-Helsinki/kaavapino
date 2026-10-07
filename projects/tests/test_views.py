from datetime import date

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from projects.models import Project
from projects.views import ProjectViewSet


@pytest.mark.unit
def test_parse_date_range_swaps_reversed_dates():
    result = ProjectViewSet()._parse_date_range(
        "2026-12-31", "2026-01-01", today=date(2026, 6, 15)
    )

    assert result == (date(2026, 1, 1), date(2026, 12, 31), 2026)


@pytest.mark.unit
def test_parse_date_range_defaults_invalid_dates():
    result = ProjectViewSet()._parse_date_range(
        "invalid", None, today=date(2026, 6, 15)
    )

    assert result == (date(2026, 1, 1), date(2026, 12, 31), 2026)


@pytest.mark.unit
def test_parse_date_range_preserves_valid_dates():
    result = ProjectViewSet()._parse_date_range(
        "2026-03-10", "2027-02-20", today=date(2026, 6, 15)
    )

    assert result == (date(2026, 3, 10), date(2027, 2, 20), 2027)


@pytest.mark.django_db
def test_project_list_filters_status_and_hides_other_users_private_projects(
    f_user, f_user2, project_factory
):
    client = APIClient()
    client.force_authenticate(user=f_user)
    public_active = project_factory(public=True)
    own_private_active = project_factory(user=f_user, public=False)
    project_factory(user=f_user2, public=False)
    public_onhold = project_factory(onhold=True)
    public_archived = project_factory(archived=True)
    url = reverse("projects-list")

    active_response = client.get(url, {"status": "active"})
    assert active_response.status_code == 200
    assert {project["id"] for project in active_response.json()["results"]} == {
        public_active.pk,
        own_private_active.pk,
    }

    onhold_response = client.get(url, {"status": "onhold"})
    assert {project["id"] for project in onhold_response.json()["results"]} == {
        public_onhold.pk,
    }

    archived_response = client.get(url, {"status": "archived"})
    assert {project["id"] for project in archived_response.json()["results"]} == {
        public_archived.pk,
    }


@pytest.mark.django_db
def test_project_list_filters_own_and_included_users(f_user, f_user2, project_factory):
    client = APIClient()
    client.force_authenticate(user=f_user)
    own_project = project_factory(user=f_user)
    other_project = project_factory(user=f_user2)
    url = reverse("projects-list")

    own_response = client.get(url, {"status": "own"})
    assert own_response.status_code == 200
    assert {project["id"] for project in own_response.json()["results"]} == {
        own_project.pk,
    }

    included_users_response = client.get(url, {"includes_users": str(f_user2.uuid)})
    assert included_users_response.status_code == 200
    assert {project["id"] for project in included_users_response.json()["results"]} == {
        other_project.pk,
    }


@pytest.mark.django_db
def test_admin_project_list_includes_other_users_private_projects(
    f_admin, f_user2, project_factory
):
    client = APIClient()
    client.force_authenticate(user=f_admin)
    private_project = project_factory(user=f_user2, public=False)

    response = client.get(reverse("projects-list"), {"status": "active"})

    assert response.status_code == 200
    assert {project["id"] for project in response.json()["results"]} == {
        private_project.pk,
    }