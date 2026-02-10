"""
Tests for deadline_utils functions.

Tests the shared deadline utility functions used for stale deadline detection and cleanup.
"""
import pytest
from projects.deadline_utils import (
    find_stale_deadline_fields,
    clean_stale_deadline_fields,
)


@pytest.mark.unit
class TestFindStaleDeadlineFields:
    """Tests for find_stale_deadline_fields function."""
    
    def test_finds_stale_fields_when_vis_bool_false(self):
        """Should detect stale date fields when visibility bool is False."""
        attribute_data = {
            'jarjestetaan_periaatteet_esillaolo_1': False,  # Group disabled
            'milloin_periaatteet_esillaolo_alkaa': '2026-01-15',  # But dates still exist
            'milloin_periaatteet_esillaolo_paattyy': '2026-01-29',
            'periaatteet_esillaolo_aineiston_maaraaika': '2026-02-03',
        }
        
        stale_data = find_stale_deadline_fields(attribute_data)
        
        assert len(stale_data) == 1
        deadline_group, vis_bool_name, stale_fields = stale_data[0]
        assert deadline_group == 'periaatteet_esillaolokerta_1'
        assert vis_bool_name == 'jarjestetaan_periaatteet_esillaolo_1'
        assert len(stale_fields) == 3
        
        field_names = [f['field'] for f in stale_fields]
        assert 'milloin_periaatteet_esillaolo_alkaa' in field_names
        assert 'milloin_periaatteet_esillaolo_paattyy' in field_names
        assert 'periaatteet_esillaolo_aineiston_maaraaika' in field_names
    
    def test_no_stale_fields_when_vis_bool_true(self):
        """Should not detect stale fields when visibility bool is True."""
        attribute_data = {
            'jarjestetaan_periaatteet_esillaolo_1': True,  # Group enabled
            'milloin_periaatteet_esillaolo_alkaa': '2026-01-15',
            'milloin_periaatteet_esillaolo_paattyy': '2026-01-29',
        }
        
        stale_data = find_stale_deadline_fields(attribute_data)
        
        assert len(stale_data) == 0
    
    def test_no_stale_fields_when_dates_are_none(self):
        """Should not detect stale fields when date fields are properly cleared."""
        attribute_data = {
            'jarjestetaan_periaatteet_esillaolo_1': False,
            # Date fields are None or missing - this is correct
        }
        
        stale_data = find_stale_deadline_fields(attribute_data)
        
        assert len(stale_data) == 0
    
    def test_handles_multiple_groups_with_stale_data(self):
        """Should detect stale fields across multiple deadline groups."""
        attribute_data = {
            'jarjestetaan_periaatteet_esillaolo_1': False,
            'milloin_periaatteet_esillaolo_alkaa': '2026-01-15',
            'jarjestetaan_oas_esillaolo_2': False,
            'milloin_oas_esillaolo_alkaa_2': '2026-03-01',
            'milloin_oas_esillaolo_paattyy_2': '2026-03-15',
        }
        
        stale_data = find_stale_deadline_fields(attribute_data)
        
        assert len(stale_data) == 2
        groups = [item[0] for item in stale_data]
        assert 'periaatteet_esillaolokerta_1' in groups
        assert 'oas_esillaolokerta_2' in groups


@pytest.mark.unit
class TestCleanStaleDeadlineFields:
    """Tests for clean_stale_deadline_fields function."""
    
    def test_clears_stale_fields_when_vis_bool_false(self):
        """Should clear date fields when visibility bool is False.
        
        KAAV-3492: Function sets ALL date fields in the group to None,
        even fields not in request, to override stale DB values during merge.
        """
        attribute_data = {
            'jarjestetaan_periaatteet_esillaolo_1': False,
            'milloin_periaatteet_esillaolo_alkaa': '2026-01-15',
            'milloin_periaatteet_esillaolo_paattyy': '2026-01-29',
            'periaatteet_esillaolo_aineiston_maaraaika': '2026-02-03',
            'other_field': 'should_not_be_touched',
        }
        
        cleared_count = clean_stale_deadline_fields(attribute_data)
        
        # 3 fields had values that got cleared
        assert cleared_count == 3
        assert 'jarjestetaan_periaatteet_esillaolo_1' in attribute_data  # vis_bool stays
        assert attribute_data['jarjestetaan_periaatteet_esillaolo_1'] is False
        # KAAV-3492: ALL fields in group are set to None (including viimeistaan_mielipiteet_periaatteista)
        assert attribute_data['milloin_periaatteet_esillaolo_alkaa'] is None
        assert attribute_data['milloin_periaatteet_esillaolo_paattyy'] is None
        assert attribute_data['periaatteet_esillaolo_aineiston_maaraaika'] is None
        assert attribute_data['viimeistaan_mielipiteet_periaatteista'] is None  # Added even if not in request
        assert attribute_data['other_field'] == 'should_not_be_touched'
    
    def test_preserves_fields_when_vis_bool_true(self):
        """Should not remove date fields when visibility bool is True."""
        attribute_data = {
            'jarjestetaan_periaatteet_esillaolo_1': True,
            'milloin_periaatteet_esillaolo_alkaa': '2026-01-15',
            'milloin_periaatteet_esillaolo_paattyy': '2026-01-29',
        }
        
        original_data = attribute_data.copy()
        cleared_count = clean_stale_deadline_fields(attribute_data)
        
        assert cleared_count == 0
        assert attribute_data == original_data
    
    def test_handles_empty_attribute_data(self):
        """Should handle None or empty attribute_data gracefully."""
        assert clean_stale_deadline_fields(None) == 0
        assert clean_stale_deadline_fields({}) == 0
    
    def test_clears_multiple_groups(self):
        """Should clear date fields for multiple disabled groups.
        
        KAAV-3492: Function sets ALL date fields in each group to None.
        """
        attribute_data = {
            'jarjestetaan_periaatteet_esillaolo_1': False,
            'milloin_periaatteet_esillaolo_alkaa': '2026-01-15',
            'milloin_periaatteet_esillaolo_paattyy': '2026-01-29',
            'jarjestetaan_oas_esillaolo_2': False,
            'milloin_oas_esillaolo_alkaa_2': '2026-03-01',
            'milloin_oas_esillaolo_paattyy_2': '2026-03-15',
            'oas_esillaolo_aineiston_maaraaika_2': '2026-02-25',
        }
        
        cleared_count = clean_stale_deadline_fields(attribute_data)
        
        # 5 fields had values that got cleared (2 from periaatteet + 3 from oas)
        assert cleared_count == 5
        # KAAV-3492: ALL fields in each group are set to None
        assert attribute_data['milloin_periaatteet_esillaolo_alkaa'] is None
        assert attribute_data['milloin_oas_esillaolo_alkaa_2'] is None
    
    def test_idempotent_cleaning(self):
        """Running cleanup twice should not cause issues.
        
        KAAV-3492: Second run should return 0 since all fields already None.
        """
        attribute_data = {
            'jarjestetaan_periaatteet_esillaolo_1': False,
            'milloin_periaatteet_esillaolo_alkaa': '2026-01-15',
        }
        
        first_count = clean_stale_deadline_fields(attribute_data)
        second_count = clean_stale_deadline_fields(attribute_data)
        
        # First run: 1 field had a value that got cleared
        assert first_count == 1
        # Second run: all fields already None, nothing to clear
        assert second_count == 0
        # KAAV-3492: Field is set to None
        assert attribute_data['milloin_periaatteet_esillaolo_alkaa'] is None

@pytest.mark.unit
class TestStaleDeadlineAdversarialCases:
    """
    Adversarial tests for stale deadline detection/cleanup.
    
    Per TESTING.md Rule #4: Always include adversarial cases:
    - missing fields / nulls / empty strings
    - unexpected shapes (extra keys, wrong types)
    - boundary values
    """
    
    def test_vis_bool_string_false_not_treated_as_false(self):
        """
        CATCHES BUG: String "false" incorrectly triggers cleanup.
        
        Frontend might send string instead of boolean.
        """
        attribute_data = {
            'jarjestetaan_periaatteet_esillaolo_1': "false",  # String, not bool
            'milloin_periaatteet_esillaolo_alkaa': '2026-01-15',
        }
        
        stale_data = find_stale_deadline_fields(attribute_data)
        
        # String "false" should NOT be treated as boolean False
        # The group should NOT be considered disabled
        assert len(stale_data) == 0, (
            "String 'false' incorrectly treated as boolean False"
        )
    
    def test_vis_bool_zero_treated_correctly(self):
        """
        CATCHES BUG: Integer 0 causes unexpected behavior.
        """
        attribute_data = {
            'jarjestetaan_periaatteet_esillaolo_1': 0,  # Integer zero
            'milloin_periaatteet_esillaolo_alkaa': '2026-01-15',
        }
        
        # 0 is falsy in Python, but not `is False`
        # The implementation should handle this gracefully
        try:
            find_stale_deadline_fields(attribute_data)
            # Test passed - no exception
        except Exception as e:
            pytest.fail(f"Integer 0 caused exception: {e}")
    
    def test_vis_bool_none_not_treated_as_disabled(self):
        """
        CATCHES BUG: None vis_bool triggers cleanup (wrong).
        
        None means "not set", not "disabled".
        """
        attribute_data = {
            'jarjestetaan_periaatteet_esillaolo_1': None,
            'milloin_periaatteet_esillaolo_alkaa': '2026-01-15',
        }
        
        stale_data = find_stale_deadline_fields(attribute_data)
        
        # None should NOT be treated as disabled
        assert len(stale_data) == 0, (
            "None vis_bool incorrectly treated as disabled"
        )
    
    def test_empty_string_date_detected_as_stale(self):
        """
        CATCHES BUG: Empty string date not detected as stale.
        
        Empty string is effectively stale data.
        """
        attribute_data = {
            'jarjestetaan_periaatteet_esillaolo_1': False,
            'milloin_periaatteet_esillaolo_alkaa': '',  # Empty string
        }
        
        # Empty string should still be cleaned up
        cleared = clean_stale_deadline_fields(attribute_data)
        
        assert cleared >= 1, (
            "Empty string date should be cleaned when group disabled"
        )
    
    def test_date_with_datetime_object_handled(self):
        """
        CATCHES BUG: Datetime object causes exception.
        
        Date might be passed as datetime instead of string.
        """
        import datetime
        
        attribute_data = {
            'jarjestetaan_periaatteet_esillaolo_1': False,
            'milloin_periaatteet_esillaolo_alkaa': datetime.date(2026, 1, 15),
        }
        
        # Should not raise exception
        try:
            stale_data = find_stale_deadline_fields(attribute_data)
            # If there's stale data, datetime should be handled
            if stale_data:
                for group, vis_bool, fields in stale_data:
                    for field_info in fields:
                        # Value might be the datetime object
                        assert field_info['value'] is not None
        except Exception as e:
            pytest.fail(f"Datetime object caused exception: {e}")
    
    def test_mixed_enabled_and_disabled_groups(self):
        """
        CATCHES BUG: Enabled group dates incorrectly cleaned.
        
        Only disabled group dates should be cleaned.
        """
        attribute_data = {
            'jarjestetaan_periaatteet_esillaolo_1': True,  # ENABLED
            'milloin_periaatteet_esillaolo_alkaa': '2026-01-15',
            'jarjestetaan_oas_esillaolo_2': False,  # DISABLED
            'milloin_oas_esillaolo_alkaa_2': '2026-03-01',
        }
        
        clean_stale_deadline_fields(attribute_data)
        
        # Only OAS date should be cleaned, not periaatteet
        assert attribute_data['milloin_periaatteet_esillaolo_alkaa'] == '2026-01-15', (
            "Enabled group date was incorrectly cleaned"
        )
        assert attribute_data['milloin_oas_esillaolo_alkaa_2'] is None
    
    def test_unknown_keys_preserved(self):
        """
        CATCHES BUG: Cleanup removes unrelated fields.
        """
        attribute_data = {
            'jarjestetaan_periaatteet_esillaolo_1': False,
            'milloin_periaatteet_esillaolo_alkaa': '2026-01-15',
            'custom_field_not_in_spec': 'preserve_me',
            'another_random_key': 12345,
        }
        
        clean_stale_deadline_fields(attribute_data)
        
        assert attribute_data['custom_field_not_in_spec'] == 'preserve_me'
        assert attribute_data['another_random_key'] == 12345
    
    def test_all_phases_handled(self):
        """
        CATCHES BUG: Some phases not in DEADLINE_GROUP_DATE_FIELDS.
        
        All phases should have their date fields defined.
        """
        from projects.deadline_utils import DEADLINE_GROUP_DATE_FIELDS
        
        # Check that we have entries for main phases
        expected_phases = ['periaatteet', 'oas', 'luonnos', 'ehdotus']
        
        all_keys = ' '.join(DEADLINE_GROUP_DATE_FIELDS.keys())
        
        for phase in expected_phases:
            assert phase in all_keys, (
                f"Phase '{phase}' missing from DEADLINE_GROUP_DATE_FIELDS. "
                f"Stale data cleanup will fail for this phase."
            )
    
    def test_lautakunta_groups_included(self):
        """
        CATCHES BUG: Lautakunta groups missing → stale lautakunta dates.
        """
        from projects.deadline_utils import DEADLINE_GROUP_DATE_FIELDS
        
        lautakunta_groups = [k for k in DEADLINE_GROUP_DATE_FIELDS.keys() if 'lautakunta' in k]
        
        assert len(lautakunta_groups) > 0, (
            "No lautakunta groups in DEADLINE_GROUP_DATE_FIELDS. "
            "Stale lautakunta date cleanup will fail."
        )