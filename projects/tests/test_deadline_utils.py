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
        """Should remove date fields when visibility bool is False."""
        attribute_data = {
            'jarjestetaan_periaatteet_esillaolo_1': False,
            'milloin_periaatteet_esillaolo_alkaa': '2026-01-15',
            'milloin_periaatteet_esillaolo_paattyy': '2026-01-29',
            'periaatteet_esillaolo_aineiston_maaraaika': '2026-02-03',
            'other_field': 'should_not_be_touched',
        }
        
        cleared_count = clean_stale_deadline_fields(attribute_data)
        
        assert cleared_count == 3
        assert 'jarjestetaan_periaatteet_esillaolo_1' in attribute_data  # vis_bool stays
        assert attribute_data['jarjestetaan_periaatteet_esillaolo_1'] is False
        assert 'milloin_periaatteet_esillaolo_alkaa' not in attribute_data  # dates removed
        assert 'milloin_periaatteet_esillaolo_paattyy' not in attribute_data
        assert 'periaatteet_esillaolo_aineiston_maaraaika' not in attribute_data
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
        """Should clear date fields for multiple disabled groups."""
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
        
        assert cleared_count == 5
        assert 'milloin_periaatteet_esillaolo_alkaa' not in attribute_data
        assert 'milloin_oas_esillaolo_alkaa_2' not in attribute_data
    
    def test_idempotent_cleaning(self):
        """Running cleanup twice should not cause issues."""
        attribute_data = {
            'jarjestetaan_periaatteet_esillaolo_1': False,
            'milloin_periaatteet_esillaolo_alkaa': '2026-01-15',
        }
        
        first_count = clean_stale_deadline_fields(attribute_data)
        second_count = clean_stale_deadline_fields(attribute_data)
        
        assert first_count == 1
        assert second_count == 0  # Nothing left to clean
        assert 'milloin_periaatteet_esillaolo_alkaa' not in attribute_data
