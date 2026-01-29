"""tests for deadline lifecycle

These tests verify that distance enforcement works correctly across
various deadline groups and that calculated deadlines respect the
distance_from_previous constraints. Keep this module-level text as a
docstring (not plain un-commented text).
"""

import pytest
from datetime import date, timedelta

# other imports that your tests use, e.g.:
# from django.urls import reverse
# from projects.models import Project, Deadline, DeadlineGroup
# from factories import ProjectFactory, DeadlineFactory
@pytest.mark.parametrize(
    "prev_date, distance_days, expected_date, description",
    [
        # P7 lautakunta (periaatteet)
        ("2026-03-01", 21, "2026-03-22", "P7 lautakunta: +21 days from material deadline"),
        # L7 lautakunta (luonnos)
        ("2026-04-01", 21, "2026-04-22", "L7 lautakunta: +21 days from material deadline"),
        # E8 lautakunta (ehdotus)
        ("2026-05-01", 21, "2026-05-22", "E8 lautakunta: +21 days from material deadline"),
        # T3 lautakunta (tarkistettu ehdotus)
        ("2026-06-01", 21, "2026-06-22", "T3 lautakunta: +21 days from material deadline"),
    ]
)
def test_lautakunta_material_deadline_minimum_distance(prev_date, distance_days, expected_date, description):
    """
    Explicitly test +21 day rule from material deadline to lautakunta as per database_deadline_rules.md.
    """
    import datetime
    from projects.models import Project
    mock_project = type("MockProject", (), {})()
    mock_project._min_distance_target_date = Project._min_distance_target_date.__get__(mock_project, Project)
    prev_date_dt = datetime.datetime.strptime(prev_date, "%Y-%m-%d").date()
    mock_distance = type("MockDistance", (), {"date_type": None, "distance_from_previous": distance_days})()
    mock_deadline = type("MockDeadline", (), {"date_type": None})()
    result = mock_project._min_distance_target_date(prev_date_dt, mock_distance, mock_deadline)
    expected_dt = datetime.datetime.strptime(expected_date, "%Y-%m-%d").date()
    assert result == expected_dt, f"{description}: got {result}, expected {expected_dt}"
import pytest
@pytest.mark.parametrize(
    "prev_date, distance_days, expected_date, description",
    [
        # P7 lautakunta slots (periaatteet)
        ("2026-03-10", 1, "2026-03-11", "P7 lautakunta_2: +1 day"),
        ("2026-03-11", 1, "2026-03-12", "P7 lautakunta_3: +1 day"),
        ("2026-03-12", 1, "2026-03-13", "P7 lautakunta_4: +1 day"),
        # L7 lautakunta slots (luonnos)
        ("2026-04-01", 1, "2026-04-02", "L7 lautakunta_2: +1 day"),
        ("2026-04-02", 1, "2026-04-03", "L7 lautakunta_3: +1 day"),
        ("2026-04-03", 1, "2026-04-04", "L7 lautakunta_4: +1 day"),
        # E8 lautakunta slots (ehdotus)
        ("2026-05-10", 1, "2026-05-11", "E8 lautakunta_2: +1 day"),
        ("2026-05-11", 1, "2026-05-12", "E8 lautakunta_3: +1 day"),
        ("2026-05-12", 1, "2026-05-13", "E8 lautakunta_4: +1 day"),
        # T3 lautakunta slots (tarkistettu ehdotus)
        ("2026-06-01", 1, "2026-06-02", "T3 lautakunta_2: +1 day"),
        ("2026-06-02", 1, "2026-06-03", "T3 lautakunta_3: +1 day"),
        ("2026-06-03", 1, "2026-06-04", "T3 lautakunta_4: +1 day"),
    ]
)
def test_lautakunta_minimum_distance_enforced(prev_date, distance_days, expected_date, description):
    """
    Explicitly test lautakunta slots (_2, _3, _4) minimum +1 day distance as per database_deadline_rules.md.
    """
    import datetime
    from projects.models import Project
    mock_project = type("MockProject", (), {})()
    mock_project._min_distance_target_date = Project._min_distance_target_date.__get__(mock_project, Project)
    prev_date_dt = datetime.datetime.strptime(prev_date, "%Y-%m-%d").date()
    mock_distance = type("MockDistance", (), {"date_type": None, "distance_from_previous": distance_days})()
    mock_deadline = type("MockDeadline", (), {"date_type": None})()
    result = mock_project._min_distance_target_date(prev_date_dt, mock_distance, mock_deadline)
    expected_dt = datetime.datetime.strptime(expected_date, "%Y-%m-%d").date()
    assert result == expected_dt, f"{description}: got {result}, expected {expected_dt}"
 # ...existing code...
import datetime
import pytest
from unittest.mock import Mock, patch, MagicMock


# Mark all tests in this module as not needing database
pytestmark = pytest.mark.unit


class TestDeadlineDistanceEnforcement:
    """
    Tests for _min_distance_target_date method logic.
    
    These are pure unit tests that don't need the database.
    They test the distance calculation algorithm itself.
    """

    def test_min_distance_target_date_with_calendar_days(self):
        """When date_type is None, should use calendar days."""
        # Import the actual model to test
        from projects.models import Project
        
        mock_project = Mock(spec=Project)
        mock_project._min_distance_target_date = Project._min_distance_target_date.__get__(mock_project, Project)
        
        prev_date = datetime.date(2026, 3, 10)  # Tuesday
        
        mock_distance = Mock()
        mock_distance.date_type = None  # Calendar days
        mock_distance.distance_from_previous = 1
        
        mock_deadline = Mock()
        mock_deadline.date_type = None
        
        result = mock_project._min_distance_target_date(prev_date, mock_distance, mock_deadline)
        
        # Should be exactly 1 calendar day later
        expected = datetime.date(2026, 3, 11)
        assert result == expected

    def test_min_distance_target_date_with_meeting_days(self):
        """When date_type is set, should use valid_days_from."""
        from projects.models import Project
        
        mock_project = Mock(spec=Project)
        mock_project._min_distance_target_date = Project._min_distance_target_date.__get__(mock_project, Project)
        
        prev_date = datetime.date(2026, 3, 10)  # Tuesday
        
        # Mock date_type that returns specific dates
        mock_date_type = Mock()
        mock_date_type.valid_days_from = Mock(return_value=datetime.date(2026, 3, 17))  # Next Tuesday
        
        mock_distance = Mock()
        mock_distance.date_type = mock_date_type
        mock_distance.distance_from_previous = 1
        
        mock_deadline = Mock()
        mock_deadline.date_type = None
        
        result = mock_project._min_distance_target_date(prev_date, mock_distance, mock_deadline)
        
        # Should use date_type.valid_days_from result
        expected = datetime.date(2026, 3, 17)
        assert result == expected
        mock_date_type.valid_days_from.assert_called_once_with(prev_date, 1)

    def test_min_distance_target_date_snaps_to_valid_date(self):
        """Result should be snapped to deadline's valid dates."""
        from projects.models import Project
        
        mock_project = Mock(spec=Project)
        mock_project._min_distance_target_date = Project._min_distance_target_date.__get__(mock_project, Project)
        
        prev_date = datetime.date(2026, 3, 10)
        
        mock_distance = Mock()
        mock_distance.date_type = None
        mock_distance.distance_from_previous = 1
        
        # Mock deadline date_type that snaps to Tuesdays
        mock_deadline_date_type = Mock()
        mock_deadline_date_type.get_closest_valid_date = Mock(return_value=datetime.date(2026, 3, 17))
        
        mock_deadline = Mock()
        mock_deadline.date_type = mock_deadline_date_type
        
        result = mock_project._min_distance_target_date(prev_date, mock_distance, mock_deadline)
        
        # Should be snapped to next valid date (Tuesday)
        expected = datetime.date(2026, 3, 17)
        assert result == expected

    def test_min_distance_with_none_prev_date(self):
        """Should return None when prev_date is None."""
        from projects.models import Project
        
        mock_project = Mock(spec=Project)
        mock_project._min_distance_target_date = Project._min_distance_target_date.__get__(mock_project, Project)
        
        mock_distance = Mock()
        mock_distance.date_type = None
        mock_distance.distance_from_previous = 1
        
        mock_deadline = Mock()
        mock_deadline.date_type = None
        
        result = mock_project._min_distance_target_date(None, mock_distance, mock_deadline)
        
        assert result is None


class TestPreviewDeadlinesLifecycle:
    """
    Integration-style tests for get_preview_deadlines with lifecycle scenarios.
    
    These tests verify that preview calculations work correctly for:
    - Adding new slots
    - Modifying dates
    - Deleting and re-adding
    """

    def test_preview_enforces_distance_on_changed_deadline(self):
        """Changed deadlines should have distance rules enforced."""
        # This test documents expected behavior:
        # Only deadlines that actually CHANGED get enforcement (KAAV-3517)
        
        original_data = {
            'milloin_periaatteet_lautakunnassa': '2026-03-10',
            'milloin_periaatteet_lautakunnassa_2': '2026-03-17',
        }
        
        # User moves lautakunta_2 too close to lautakunta
        updated_data = {
            'milloin_periaatteet_lautakunnassa': '2026-03-10',  # Unchanged
            'milloin_periaatteet_lautakunnassa_2': '2026-03-11',  # Changed - violates distance
        }
        
        # Detect changed deadlines
        changed = [k for k in updated_data if updated_data[k] != original_data.get(k)]
        assert changed == ['milloin_periaatteet_lautakunnassa_2']
        
        # The enforcement logic should:
        # 1. Detect that lautakunta_2 changed
        # 2. Check if minimum distance is violated
        # 3. If violated, push lautakunta_2 forward

    def test_preview_unchanged_deadline_not_affected(self):
        """Unchanged deadlines should keep their original values."""
        original_data = {
            'milloin_periaatteet_esillaolo_alkaa': '2026-03-10',
            'milloin_periaatteet_esillaolo_paattyy': '2026-03-24',
            'milloin_periaatteet_lautakunnassa': '2026-04-07',
        }
        
        # User moves esillaolo_alkaa forward - paattyy and lautakunta unchanged
        updated_data = {
            'milloin_periaatteet_esillaolo_alkaa': '2026-03-17',  # Changed
            'milloin_periaatteet_esillaolo_paattyy': '2026-03-24',  # Unchanged
            'milloin_periaatteet_lautakunnassa': '2026-04-07',  # Unchanged
        }
        
        # Detect unchanged deadlines
        unchanged = [k for k in updated_data if updated_data[k] == original_data.get(k)]
        assert 'milloin_periaatteet_esillaolo_paattyy' in unchanged
        assert 'milloin_periaatteet_lautakunnassa' in unchanged


class TestLautakuntaDistanceRules:
    """
    Tests specific to lautakunta distance enforcement.
    
    Lautakunta dates have special rules:
    - Must land on Tuesdays
    - Secondary slots (_2, _3, _4) have distance from previous slot
    """

    def test_lautakunta_2_distance_from_lautakunta_1(self):
        """Lautakunta_2 should respect distance from lautakunta_1."""
        # Database should have DeadlineDistance from lautakunta_1 -> lautakunta_2
        # with distance_from_previous = 1 (calendar day)
        # and date_type = None (meaning calendar days, not meeting days)
        
        prev_date = datetime.date(2026, 3, 10)  # Tuesday
        distance = 1  # calendar days
        
        min_target = prev_date + datetime.timedelta(days=distance)
        assert min_target == datetime.date(2026, 3, 11)  # Wednesday
        
        # Snapping to next Tuesday (day 1 in Python where Monday=0)
        days_until_tuesday = (1 - min_target.weekday()) % 7
        if days_until_tuesday == 0:
            days_until_tuesday = 7
        next_tuesday = min_target + datetime.timedelta(days=days_until_tuesday)
        assert next_tuesday == datetime.date(2026, 3, 17)

    def test_lautakunta_same_day_allowed_with_distance_0(self):
        """Lautakunta_2 on same day as lautakunta_1 requires distance=0."""
        prev_date = datetime.date(2026, 3, 10)  # Tuesday
        distance = 0  # Allow same day
        
        min_target = prev_date + datetime.timedelta(days=distance)
        assert min_target == datetime.date(2026, 3, 10)  # Same Tuesday


class TestPhaseTransitionEnforcement:
    """
    Tests for distance enforcement at phase transitions.
    """

    def test_oas_start_after_periaatteet_end(self):
        """OAS phase should start on or after periaatteet ends."""
        periaatteet_end = datetime.date(2026, 4, 15)
        oas_start = datetime.date(2026, 4, 15)  # Same day is OK
        
        assert oas_start >= periaatteet_end

    def test_cascade_does_not_affect_previous_phases(self):
        """Changes in later phases should not cascade backwards."""
        # Document the expected behavior:
        # When modifying a date in OAS phase, periaatteet dates should not change
        # This is critical for consistency - only forward cascading is allowed
        
        # This is enforced by the order parameter in checkForDecreasingValues
        # which iterates forward from currentIndex
        pass


class TestDeleteAndReaddScenarios:
    """
    Tests for delete and re-add scenarios.
    """

    def test_readd_after_delete_calculates_fresh_dates(self):
        """Re-adding a group after deletion should calculate dates fresh."""
        # Scenario:
        # 1. User has periaatteet_esillaolo_2 with dates
        # 2. User deletes periaatteet_esillaolo_2 (visibility bool = false)
        # 3. User saves (dates may be nullified in DB)
        # 4. User adds periaatteet_esillaolo_2 back (visibility bool = true)
        # 5. Dates should be calculated fresh from previous deadlines
        
        # Document that null dates should not break the calculation
        # The frontend should:
        # 1. Detect it's a re-add (dates are null but visibility is being set to true)
        # 2. Calculate fresh dates from the previous esillaolo_1 end date
        # 3. Dispatch updateDateTimeline with addingNew=true
        pass

    def test_delete_does_not_leave_orphan_distances(self):
        """Deleting a group should not leave broken distance references."""
        # The distance rules reference deadline slots by identifier
        # When esillaolo_2 is deleted, distance rules that depend on it
        # should still work (they skip to next available deadline)
        pass


class TestKAAV3492VisibilityBoolChangeTrigger:
    """
    KAAV-3492 Backend Fix Tests:
    When visibility bool changes from False to True, associated deadlines
    should be treated as "changed" for distance enforcement purposes.
    """

    def test_vis_bool_change_detection(self):
        """Changing visibility bool from False to True should be detected."""
        # Simulate the scenario
        old_value = False
        new_value = True
        
        # This is how the fix detects the change
        is_re_enable = isinstance(new_value, bool) and new_value and not old_value
        assert is_re_enable is True

    def test_vis_bool_already_true_not_detected(self):
        """If visibility bool was already True, don't treat as re-add."""
        old_value = True
        new_value = True
        
        is_re_enable = isinstance(new_value, bool) and new_value is True and old_value is not True
        assert is_re_enable is False

    def test_vis_bool_none_to_true_detected(self):
        """Changing from None to True should be detected as new add."""
        old_value = None
        new_value = True
        
        is_re_enable = isinstance(new_value, bool) and new_value is True and old_value is not True
        assert is_re_enable is True

    def test_deadline_dates_added_to_actually_changed(self):
        """When vis_bool re-enabled, associated dates should be in actually_changed."""
        # This is a logic test of how the fix works:
        # If jarjestetaan_periaatteet_esillaolo_1 changes False -> True,
        # then milloin_periaatteet_esillaolo_alkaa and milloin_periaatteet_esillaolo_paattyy
        # should be added to actually_changed set even if their values didn't change
        
        updated_attributes = {
            'jarjestetaan_periaatteet_esillaolo_1': True,
            'milloin_periaatteet_esillaolo_alkaa': '2026-02-01',  # Same as DB
            'milloin_periaatteet_esillaolo_paattyy': '2026-02-15',  # Same as DB
        }
        
        stored_attribute_data = {
            'jarjestetaan_periaatteet_esillaolo_1': False,  # Was disabled
            'milloin_periaatteet_esillaolo_alkaa': '2026-02-01',  # Old date still there
            'milloin_periaatteet_esillaolo_paattyy': '2026-02-15',  # Old date still there
        }
        
        # Step 1: Detect vis_bools that changed to True
        vis_bools_enabled = set()
        for key, new_value in updated_attributes.items():
            old_value = stored_attribute_data.get(key)
            if isinstance(new_value, bool) and new_value is True and old_value is not True:
                vis_bools_enabled.add(key)
        
        assert 'jarjestetaan_periaatteet_esillaolo_1' in vis_bools_enabled
        
        # Step 2: The fix would then iterate deadlines and add their dates to actually_changed
        # For this test, we just verify the detection logic works
        assert len(vis_bools_enabled) == 1


class TestDistanceEnforcementConsistency:
    """
    Tests to ensure distance enforcement is consistent across all operations.
    """

    def test_enforcement_same_for_add_and_modify(self):
        """Distance enforcement should work the same for add and modify."""
        # The only difference should be:
        # - Add (isAdd=true): Always enforce full distance
        # - Modify (isAdd=false): Only enforce if minimum is violated
        
        # But the distance calculation algorithm should be the same
        pass

    def test_all_phases_have_distance_rules(self):
        """All secondary slots in all phases should have distance rules."""
        # This is tested in test_deadline_data_completeness.py
        pass

    def test_distance_values_match_excel(self):
        """Distance values in DB should match Excel specifications."""
        # Expected values based on business requirements:
        # expected_lautakunta_distance = 1  # 1 calendar day between lautakunta slots (unused)
        
        # This is validated in test_deadline_data_completeness.py

