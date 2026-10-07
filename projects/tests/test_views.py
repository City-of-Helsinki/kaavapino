from datetime import date

import pytest

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