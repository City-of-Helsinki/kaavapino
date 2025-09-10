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
        report_factory(is_admin_report=False)
        report = report_factory(is_admin_report=False)
        url = reverse("report-list")

        response = self.client.get(url)

        assert response.status_code == 200

        results = response.json()["results"]
        assert len(results) == 2
        assert any(r["id"] == report.id for r in results)

    def test_for_admin_user__admin_reports_are_listed(self, f_admin, report_factory):
        self.client.force_authenticate(user=f_admin)
        report = report_factory(is_admin_report=True)
        url = reverse("report-list")

        response = self.client.get(url)

        assert response.status_code == 200
        results = response.json()["results"]
        assert len(results) == 1
        assert results[0]["id"] == report.id

    def test_for_normal_user__admin_reports_are_not_listed(
        self, f_user, report_factory
    ):
        self.client.force_authenticate(user=f_user)
        report_factory(is_admin_report=True)
        url = reverse("report-list")

        response = self.client.get(url)

        assert response.status_code == 200
        assert len(response.json()["results"]) == 0

    def test_when_fetching_report_types__should_include_available_filters(
        self, f_user, report_factory, report_filter_factory
    ):
        self.client.force_authenticate(user=f_user)
        report = report_factory()
        report_filter = report_filter_factory()
        report_filter.reports.set([report])
        url = reverse("report-list")

        response = self.client.get(url)

        report_definition = response.json()["results"][0]
        assert report_definition["filters"] == [{
            "name": report_filter.name,
            "identifier": report_filter.identifier,
            "type": report_filter.type,
            "input_type": "string",
            "choices": None,
        }]


@pytest.mark.django_db()
class TestFetchingReport:
    client = APIClient()

    def test_normal_user__can_fetch_report(self, f_user, report):
        self.client.force_authenticate(user=f_user)
        url = reverse("report-detail", kwargs={"pk": report.pk})

        response = self.client.get(url)

        assert response.status_code == 202
        assert response.json()["detail"] != None

    def test_admin_user__can_fetch_admin_report(self, f_admin, report_factory):
        self.client.force_authenticate(user=f_admin)
        report = report_factory(is_admin_report=True)
        url = reverse("report-detail", kwargs={"pk": report.pk})

        response = self.client.get(url)

        assert response.status_code == 202

    def test_normal_user__cannot_fetch_admin_report(self, f_user, report_factory):
        self.client.force_authenticate(user=f_user)
        report = report_factory(is_admin_report=True)
        url = reverse("report-detail", kwargs={"pk": report.pk})

        response = self.client.get(url)

        assert response.status_code == 404

