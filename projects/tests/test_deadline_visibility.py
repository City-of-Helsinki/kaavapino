"""
Unit tests for deadline visibility logic in get_preview_deadlines.

KAAV-3492: When a visibility boolean is False (e.g., jarjestetaan_oas_esillaolo_2 = False),
the corresponding deadline group should be hidden and NOT appear in the response.
"""
import pytest
from unittest.mock import Mock, MagicMock, patch
from projects.serializers.utils import VIS_BOOL_MAP, get_dl_vis_bool_name


class TestVisibilityBooleanMapping:
    """Test that VIS_BOOL_MAP correctly maps deadline groups to visibility booleans."""
    
    def test_oas_esillaolokerta_2_maps_to_jarjestetaan_oas_esillaolo_2(self):
        """oas_esillaolokerta_2 should map to jarjestetaan_oas_esillaolo_2"""
        assert VIS_BOOL_MAP.get('oas_esillaolokerta_2') == 'jarjestetaan_oas_esillaolo_2'
    
    def test_get_dl_vis_bool_name_returns_correct_value(self):
        """get_dl_vis_bool_name should return the visibility boolean name."""
        assert get_dl_vis_bool_name('oas_esillaolokerta_2') == 'jarjestetaan_oas_esillaolo_2'
        assert get_dl_vis_bool_name('oas_esillaolokerta_1') == 'jarjestetaan_oas_esillaolo_1'
        assert get_dl_vis_bool_name('oas_esillaolokerta_3') == 'jarjestetaan_oas_esillaolo_3'


class TestIsDeadlineVisible:
    """Test the is_deadline_visible helper function logic."""
    
    def test_deadline_with_visibility_false_should_be_hidden(self):
        """
        When jarjestetaan_oas_esillaolo_2 = False in the data,
        a deadline with deadlinegroup='oas_esillaolokerta_2' should be hidden.
        """
        # Simulate the data that would be in updated_attribute_data
        updated_attribute_data = {
            'jarjestetaan_oas_esillaolo_1': True,
            'jarjestetaan_oas_esillaolo_2': False,  # THIS IS FALSE!
            'milloin_oas_esillaolo_alkaa_2': '2026-09-10',
            'milloin_oas_esillaolo_paattyy_2': '2026-09-30',
        }
        
        # Create a mock deadline with the correct deadlinegroup
        dl = Mock()
        dl.deadlinegroup = 'oas_esillaolokerta_2'
        dl.attribute = Mock()
        dl.attribute.identifier = 'milloin_oas_esillaolo_paattyy_2'
        
        # This is the logic from get_preview_deadlines - replicate it exactly
        def is_deadline_visible(dl):
            if not hasattr(dl, 'deadlinegroup') or not dl.deadlinegroup:
                return True
            vis_bool = get_dl_vis_bool_name(dl.deadlinegroup)
            if not vis_bool:
                return True
            vis_value = updated_attribute_data.get(vis_bool)
            if vis_value is False:
                return False
            return True
        
        # The deadline should NOT be visible
        result = is_deadline_visible(dl)
        assert result is False, f"Expected False but got {result}. vis_bool={get_dl_vis_bool_name(dl.deadlinegroup)}, value={updated_attribute_data.get(get_dl_vis_bool_name(dl.deadlinegroup))}"
    
    def test_deadline_with_visibility_true_should_be_visible(self):
        """
        When jarjestetaan_oas_esillaolo_1 = True in the data,
        a deadline with deadlinegroup='oas_esillaolokerta_1' should be visible.
        """
        updated_attribute_data = {
            'jarjestetaan_oas_esillaolo_1': True,
        }
        
        dl = Mock()
        dl.deadlinegroup = 'oas_esillaolokerta_1'
        dl.attribute = Mock()
        dl.attribute.identifier = 'milloin_oas_esillaolo_paattyy'
        
        def is_deadline_visible(dl):
            if not hasattr(dl, 'deadlinegroup') or not dl.deadlinegroup:
                return True
            vis_bool = get_dl_vis_bool_name(dl.deadlinegroup)
            if not vis_bool:
                return True
            vis_value = updated_attribute_data.get(vis_bool)
            if vis_value is False:
                return False
            return True
        
        result = is_deadline_visible(dl)
        assert result is True
    
    def test_deadline_without_group_should_be_visible(self):
        """Deadlines without a deadlinegroup should always be visible."""
        updated_attribute_data = {}
        
        dl = Mock()
        dl.deadlinegroup = None
        
        def is_deadline_visible(dl):
            if not hasattr(dl, 'deadlinegroup') or not dl.deadlinegroup:
                return True
            vis_bool = get_dl_vis_bool_name(dl.deadlinegroup)
            if not vis_bool:
                return True
            vis_value = updated_attribute_data.get(vis_bool)
            if vis_value is False:
                return False
            return True
        
        result = is_deadline_visible(dl)
        assert result is True


class TestDeadlineGroupAttribute:
    """Test that real Deadline objects have the deadlinegroup attribute."""
    
    @pytest.mark.django_db
    def test_deadline_has_deadlinegroup_field(self):
        """Check that the Deadline model has a deadlinegroup field."""
        from projects.models import Deadline
        
        # Check if the field exists
        field_names = [f.name for f in Deadline._meta.get_fields()]
        assert 'deadlinegroup' in field_names, f"Deadline model missing 'deadlinegroup' field. Fields: {field_names}"
    
    @pytest.mark.django_db  
    def test_oas_esillaolo_2_deadline_has_correct_group(self):
        """Check that milloin_oas_esillaolo_paattyy_2 deadline has the correct group."""
        from projects.models import Deadline, Attribute
        
        try:
            attr = Attribute.objects.get(identifier='milloin_oas_esillaolo_paattyy_2')
            deadlines = Deadline.objects.filter(attribute=attr)
            
            for dl in deadlines:
                print(f"Deadline: {dl}, deadlinegroup: {dl.deadlinegroup}")
                # It should be 'oas_esillaolokerta_2' for the visibility to work
                assert dl.deadlinegroup == 'oas_esillaolokerta_2', \
                    f"Expected deadlinegroup='oas_esillaolokerta_2' but got '{dl.deadlinegroup}'"
        except Attribute.DoesNotExist:
            pytest.skip("Attribute milloin_oas_esillaolo_paattyy_2 not found in database")
        except Deadline.DoesNotExist:
            pytest.skip("No deadline found for milloin_oas_esillaolo_paattyy_2")
