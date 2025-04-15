import pytest
from django.urls import reverse
from rest_framework.test import APIClient

@pytest.mark.django_db
def test_preview_does_not_override_confirmed_fields(project_factory):
    # 🔧 Luo testiprojekti, jossa attribute_data on asetettu valmiiksi
    project = project_factory(
        attribute_data={
            "periaatteet_esillaolo_aineiston_maaraaika": "2025-04-01",
            "milloin_periaatteet_esillaolo_alkaa": "2025-04-02",
        }
    )

    url = reverse("project-detail", kwargs={"pk": project.id}) + "?fake=true"
    client = APIClient()

    payload = {
        "attribute_data": {
            "periaatteet_esillaolo_aineiston_maaraaika": "2099-12-31",
            "milloin_periaatteet_esillaolo_alkaa": "2099-12-30",
            "milloin_ehdotuksen_nahtavilla_alkaa_iso": "2030-01-01",  # ✅ saa muuttua
        },
        "confirmed_fields": [
            "periaatteet_esillaolo_aineiston_maaraaika",
            "milloin_periaatteet_esillaolo_alkaa"
        ]
    }

    response = client.patch(url, data=payload, format="json")
    assert response.status_code == 200

    data = response.json()

    # ✅ Varmista että confirmed-kenttiä EI ylikirjoitettu
    assert data["attribute_data"]["periaatteet_esillaolo_aineiston_maaraaika"] == "2025-04-01"
    assert data["attribute_data"]["milloin_periaatteet_esillaolo_alkaa"] == "2025-04-02"

    # ✅ Mutta muu kenttä saa muuttua
    assert data["attribute_data"]["milloin_ehdotuksen_nahtavilla_alkaa_iso"] == "2030-01-01"
