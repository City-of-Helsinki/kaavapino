"""
Tests for KAAV-3492 / KAAV-3517 PR changes

PR #362 (kaavapino) - Backend changes:
- KAAV-3492: Validation speed up (30s→2s) + distance rules skipped when conditions unmet
- KAAV-3517: Fix confirmed fields not protected during deadline recalculation

PR #658 (kaavapino-ui) - Frontend changes covered separately

Key methods tested:
- _enforce_distance_requirements(): Skips distance rules whose conditions aren't met
- _set_calculated_deadline(): Respect confirmed_fields during calculation
"""
import datetime
import pytest
from unittest.mock import Mock

from projects.models import (
    Deadline,
    DeadlineDistance,
    Project,
)


# =============================================================================
# KAAV-3517: Confirmed fields protection tests
# =============================================================================

class TestSetCalculatedDeadlineConfirmedFields:
    """
    Tests for _set_calculated_deadline respecting confirmed_fields.
    
    When a deadline is in confirmed_fields, the original value should be
    preserved and not overwritten by the calculated value.
    """

    @pytest.fixture
    def mock_project_for_confirmed(self):
        """Create mock project for confirmed fields testing."""
        project = Mock(spec=Project)
        project.attribute_data = {
            "periaatteet_lautakunta_aineiston_maaraaika": datetime.date(2026, 5, 15),
        }
        project._set_calculated_deadline = Project._set_calculated_deadline.__get__(project, Project)
        project._enforce_distance_requirements = Mock(return_value=datetime.date(2026, 6, 1))
        project.deadlines = Mock()
        project.deadlines.filter = Mock(return_value=Mock(exists=Mock(return_value=True)))
        return project

    @pytest.fixture
    def mock_deadline_with_attribute(self):
        """Create mock deadline with attribute."""
        deadline = Mock(spec=Deadline)
        deadline.attribute = Mock()
        deadline.attribute.identifier = "periaatteet_lautakunta_aineiston_maaraaika"
        return deadline

    def test_confirmed_field_preserves_original_value(self, mock_project_for_confirmed, mock_deadline_with_attribute):
        """Confirmed field should return original value, not calculated."""
        confirmed_fields = {"periaatteet_lautakunta_aineiston_maaraaika": True}
        
        result = mock_project_for_confirmed._set_calculated_deadline(
            deadline=mock_deadline_with_attribute,
            date=datetime.date(2026, 6, 1),  # Calculated value
            user=None,
            preview=True,
            preview_attribute_data={},
            confirmed_fields=confirmed_fields
        )
        
        # Should return original value from attribute_data, not the calculated value
        assert result == datetime.date(2026, 5, 15)

    def test_non_confirmed_field_uses_calculated_value(self, mock_project_for_confirmed, mock_deadline_with_attribute):
        """Non-confirmed field should use calculated value."""
        confirmed_fields = {}  # Field not in confirmed_fields
        
        result = mock_project_for_confirmed._set_calculated_deadline(
            deadline=mock_deadline_with_attribute,
            date=datetime.date(2026, 6, 1),
            user=None,
            preview=True,
            preview_attribute_data={},
            confirmed_fields=confirmed_fields
        )
        
        # Should use calculated value (after distance enforcement)
        assert result == datetime.date(2026, 6, 1)

    def test_confirmed_field_with_empty_dict(self, mock_project_for_confirmed, mock_deadline_with_attribute):
        """Empty confirmed_fields should allow calculated value."""
        result = mock_project_for_confirmed._set_calculated_deadline(
            deadline=mock_deadline_with_attribute,
            date=datetime.date(2026, 6, 1),
            user=None,
            preview=True,
            preview_attribute_data={},
            confirmed_fields={}
        )
        
        assert result == datetime.date(2026, 6, 1)


# =============================================================================
# KAAV-3492: Distance rule condition checking tests  
# =============================================================================

class TestDistanceRuleConditionChecking:
    """
    Tests for skipping distance rules when conditions are not met.
    
    The _enforce_distance_requirements should skip distance rules
    that have check_conditions returning False.
    """

    @pytest.fixture
    def mock_project_for_conditions(self):
        """Create mock project for condition testing."""
        project = Mock(spec=Project)
        project.attribute_data = {}
        project._coerce_date_value = Project._coerce_date_value.__get__(project, Project)
        project._enforce_distance_requirements = Project._enforce_distance_requirements.__get__(project, Project)
        project._resolve_deadline_date = Mock(return_value=datetime.date(2026, 1, 1))
        project._min_distance_target_date = Mock(return_value=datetime.date(2026, 3, 1))
        return project

    def test_skips_distance_rule_when_condition_false(self, mock_project_for_conditions):
        """Should skip distance rule when check_conditions returns False."""
        # Create distance rule with condition that returns False
        distance_rule = Mock(spec=DeadlineDistance)
        distance_rule.previous_deadline = Mock()
        distance_rule.previous_deadline.attribute = Mock()
        distance_rule.previous_deadline.attribute.identifier = "some_deadline"
        distance_rule.distance_from_previous = 30
        distance_rule.check_conditions = Mock(return_value=False)  # Condition NOT met
        
        deadline = Mock(spec=Deadline)
        deadline.attribute = Mock()
        deadline.attribute.identifier = "test_deadline"
        deadline.date_type = None
        deadline.distances_to_previous = Mock()
        deadline.distances_to_previous.all = Mock(return_value=[distance_rule])
        
        current_date = datetime.date(2026, 2, 1)
        
        result = mock_project_for_conditions._enforce_distance_requirements(
            deadline,
            current_date,
            preview_attribute_data={}
        )
        
        # Should return unchanged date since condition was not met
        assert result == current_date
        # _min_distance_target_date should NOT have been called
        mock_project_for_conditions._min_distance_target_date.assert_not_called()

    def test_applies_distance_rule_when_condition_true(self, mock_project_for_conditions):
        """Should apply distance rule when check_conditions returns True."""
        # Create distance rule with condition that returns True
        distance_rule = Mock(spec=DeadlineDistance)
        distance_rule.previous_deadline = Mock()
        distance_rule.previous_deadline.attribute = Mock()
        distance_rule.previous_deadline.attribute.identifier = "some_deadline"
        distance_rule.distance_from_previous = 30
        distance_rule.check_conditions = Mock(return_value=True)  # Condition met
        
        deadline = Mock(spec=Deadline)
        deadline.attribute = Mock()
        deadline.attribute.identifier = "test_deadline"
        deadline.date_type = None
        deadline.distances_to_previous = Mock()
        deadline.distances_to_previous.all = Mock(return_value=[distance_rule])
        
        current_date = datetime.date(2026, 2, 1)
        
        result = mock_project_for_conditions._enforce_distance_requirements(
            deadline,
            current_date,
            preview_attribute_data={}
        )
        
        # _min_distance_target_date should have been called and result pushed forward
        assert result == datetime.date(2026, 3, 1)
