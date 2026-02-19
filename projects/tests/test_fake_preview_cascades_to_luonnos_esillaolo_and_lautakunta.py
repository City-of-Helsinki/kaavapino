import datetime
import secrets

import pytest
from django.contrib.auth import get_user_model
from django.db.models.signals import pre_save

from projects.models.project import Project, ProjectSubtype, ProjectType
from projects.signals.handlers import save_attribute_data_subtype

pytestmark = pytest.mark.django_db

password = secrets.token_urlsafe(24)


def _d(s: str) -> datetime.date:
    y, m, d = s.split("-")
    return datetime.date(int(y), int(m), int(d))


def _preview_to_identifier_map(preview: dict) -> dict:
    """
    get_preview_deadlines returns a dict where keys are usually Deadline objects
    (with .attribute.identifier), and some keys can be strings (visibility bools etc.).
    Convert to {identifier: date} for Deadline keys.
    """
    out = {}
    for key, value in preview.items():
        if hasattr(key, "attribute") and getattr(key, "attribute", None):
            ident = key.attribute.identifier
            if isinstance(value, datetime.date):
                out[ident] = value
            elif isinstance(value, str):
                out[ident] = _d(value)
    return out


def _get_seeded_subtype_or_skip() -> tuple[ProjectType, ProjectSubtype]:
    """
    This regression test requires real deadline templates (seed/fixture data).
    Creating a brand-new subtype in the test DB usually produces *zero* deadlines,
    which makes preview maps empty.

    Prefer an existing (seeded) subtype. If none exists, skip with a clear reason.
    """
    ptype, _ = ProjectType.objects.get_or_create(name="asemakaava")

    # Prefer something that looks like "XL" if your seed data has it; otherwise any subtype.
    subtype = (
        ProjectSubtype.objects.filter(project_type=ptype, name__icontains="XL").first()
        or ProjectSubtype.objects.filter(project_type=ptype).first()
    )

    if not subtype:
        pytest.skip(
            "No ProjectSubtype found for ProjectType('asemakaava') in test DB. "
            "This test requires seeded/fixture deadline templates."
        )

    return ptype, subtype


def test_fake_preview_cascades_to_luonnos_esillaolo_and_lautakunta():
    """
    Regression (KAAV-3492):
    Periaatteet moves -> OAS moves -> Luonnos esilläolo + lautakunta move in fake preview result.

    This test intentionally bypasses the API (ProjectPermissions caused 403),
    and asserts directly against get_preview_deadlines() output.
    """

    # Disconnect signal that assumes instance.phase exists during save() for new projects
    pre_save.disconnect(save_attribute_data_subtype, sender=Project)
    try:
        User = get_user_model()
        user = User.objects.create_user(username="test", password=password)

        # IMPORTANT: use seeded subtype that actually has deadline templates
        _ptype, subtype = _get_seeded_subtype_or_skip()

        project = Project.objects.create(
            user=user,
            name="regression-kaav-3492",
            subtype=subtype,
            create_principles=True,
            create_draft=True,
            attribute_data={
                "projektin_kaynnistys_pvm": "2026-01-30",
                "kaavaprosessin_kokoluokka": "XL",
                # Make the groups visible so deadlines exist
                "jarjestetaan_oas_esillaolo_1": True,
                "jarjestetaan_periaatteet_esillaolo_1": True,
                "jarjestetaan_luonnos_esillaolo_1": True,
                # Phase created flags
                "periaatteet_luotu": True,
                "luonnos_luotu": True,
            },
        )

        # Ensure baseline deadlines exist on the project
        project.update_deadlines(
            user=user,
            initial=True,
            preview_attributes=project.attribute_data,
            confirmed_fields={},
        )

        # If templates are missing, update_deadlines won't generate anything -> skip instead of failing noisily.
        if hasattr(project, "deadlines") and not project.deadlines.exists():
            pytest.skip(
                "No deadlines were generated for the chosen subtype. "
                "Test DB likely missing seeded/fixture deadline templates."
            )

        # --- Baseline preview
        preview0 = project.get_preview_deadlines(
            subtype=subtype,
            updated_attributes=project.attribute_data,
            confirmed_fields=[],
        )
        base = _preview_to_identifier_map(preview0)

        # Target identifiers from your real bug focus
        assert "milloin_luonnos_esillaolo_alkaa" in base, (
            "Baseline preview missing milloin_luonnos_esillaolo_alkaa "
            "(likely missing deadline templates/attributes in test DB)"
        )
        assert "milloin_kaavaluonnos_lautakunnassa" in base, (
            "Baseline preview missing milloin_kaavaluonnos_lautakunnassa "
            "(likely missing deadline templates/attributes in test DB)"
        )

        base_esillaolo = base["milloin_luonnos_esillaolo_alkaa"]
        base_lautakunta = base["milloin_kaavaluonnos_lautakunnassa"]

        # --- Trigger cascade by moving Periaatteet forward
        changed_attrs = dict(project.attribute_data)
        changed_attrs["periaatteet_lautakunta_aineiston_maaraaika"] = "2028-06-01"

        preview1 = project.get_preview_deadlines(
            subtype=subtype,
            updated_attributes=changed_attrs,
            confirmed_fields=[],
        )
        after = _preview_to_identifier_map(preview1)

        assert "milloin_luonnos_esillaolo_alkaa" in after
        assert "milloin_kaavaluonnos_lautakunnassa" in after

        after_esillaolo = after["milloin_luonnos_esillaolo_alkaa"]
        after_lautakunta = after["milloin_kaavaluonnos_lautakunnassa"]

        # Must not go backwards
        assert after_esillaolo >= base_esillaolo
        assert after_lautakunta >= base_lautakunta

        # Strong regression expectation: should move forward in this scenario
        assert after_esillaolo > base_esillaolo
        assert after_lautakunta > base_lautakunta

    finally:
        pre_save.connect(save_attribute_data_subtype, sender=Project)
