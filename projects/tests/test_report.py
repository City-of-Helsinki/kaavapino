import pytest
from django.urls import reverse
from rest_framework.test import APIClient


@pytest.mark.django_db()
class TestListingReportTypes:
    client = APIClient()

    def test_for_a_user__all_normal_reports_should_be_listed(
        self, f_user, report_factory
    ):
        self.client.force_authenticate(user=f_user)
        report_factory()
        report = report_factory()
        url = reverse("report-list")

        response = self.client.get(url)

        assert response.status_code == 200
        assert len(response.json()) == 2
        assert any(r["id"] == report.id for r in response.json())

    def test_for_admin_user__admin_reports_are_listed(self, f_admin, report_factory):
        self.client.force_authenticate(user=f_admin)
        report = report_factory(is_admin_report=True)
        url = reverse("report-list")

        response = self.client.get(url)

        assert response.status_code == 200
        assert len(response.json()) == 1
        assert response.json()[0]["id"] == report.id

    def test_for_normal_user__admin_reports_are_not_listed(
        self, f_user, report_factory
    ):
        self.client.force_authenticate(user=f_user)
        report_factory(is_admin_report=True)
        url = reverse("report-list")

        response = self.client.get(url)

        assert response.status_code == 200
        assert len(response.json()) == 0

    def test_when_fetching_report_types__should_include_available_filters(
        self, f_user, report_factory
    ):
        """Filters for default project fields are included"""
        self.client.force_authenticate(user=f_user)
        report_factory()
        url = reverse("report-list")

        response = self.client.get(url)

        report_definition = response.json()[0]
        user_filter = None
        for f in report_definition["filters"]:
            if f["identifier"] == "user__uuid":
                user_filter = f

        assert user_filter == {
            "identifier": "user__uuid",
            "type": "uuid",
            "lookup": "exact",
        }


@pytest.mark.django_db()
class TestFetchingReport:
    client = APIClient()

    def test_normal_user__can_fetch_report(self, f_user, report_factory):
        self.client.force_authenticate(user=f_user)
        report = report_factory()
        url = reverse("report-detail", kwargs={"pk": report.pk})

        response = self.client.get(url)

        assert response.status_code == 200
        assert response["content-type"] == "text/csv; header=present; charset=UTF-8"
        assert "attachment" in response["content-disposition"]

    def test_admin_user__can_fetch_admin_report(self, f_admin, report_factory):
        self.client.force_authenticate(user=f_admin)
        report = report_factory(is_admin_report=True)
        url = reverse("report-detail", kwargs={"pk": report.pk})

        response = self.client.get(url)

        assert response.status_code == 200

    def test_normal_user__cannot_fetch_admin_report(self, f_user, report_factory):
        self.client.force_authenticate(user=f_user)
        report = report_factory(is_admin_report=True)
        url = reverse("report-detail", kwargs={"pk": report.pk})

        response = self.client.get(url)

        assert response.status_code == 404

