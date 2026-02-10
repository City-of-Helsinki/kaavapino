"""
Shared utilities for deadline management.

This module contains constants and functions used across deadline-related
commands and features, particularly for KAAV-3492 stale deadline detection/cleanup.
"""
from projects.serializers.utils import VIS_BOOL_MAP


# Map each deadline group to its associated date fields
# These are the fields that should be cleared when the group is deleted
DEADLINE_GROUP_DATE_FIELDS = {
    # Periaatteet esilläolo
    'periaatteet_esillaolokerta_1': [
        'milloin_periaatteet_esillaolo_alkaa',
        'milloin_periaatteet_esillaolo_paattyy',
        'periaatteet_esillaolo_aineiston_maaraaika',
    ],
    'periaatteet_esillaolokerta_2': [
        'milloin_periaatteet_esillaolo_alkaa_2',
        'milloin_periaatteet_esillaolo_paattyy_2',
        'periaatteet_esillaolo_aineiston_maaraaika_2',
    ],
    'periaatteet_esillaolokerta_3': [
        'milloin_periaatteet_esillaolo_alkaa_3',
        'milloin_periaatteet_esillaolo_paattyy_3',
        'periaatteet_esillaolo_aineiston_maaraaika_3',
    ],
    # Periaatteet lautakunta
    'periaatteet_lautakuntakerta_1': [
        'milloin_periaatteet_lautakunnassa',
        'periaatteet_lautakunta_aineiston_maaraaika',
    ],
    'periaatteet_lautakuntakerta_2': [
        'milloin_periaatteet_lautakunnassa_2',
        'periaatteet_lautakunta_aineiston_maaraaika_2',
    ],
    'periaatteet_lautakuntakerta_3': [
        'milloin_periaatteet_lautakunnassa_3',
        'periaatteet_lautakunta_aineiston_maaraaika_3',
    ],
    'periaatteet_lautakuntakerta_4': [
        'milloin_periaatteet_lautakunnassa_4',
        'periaatteet_lautakunta_aineiston_maaraaika_4',
    ],
    # OAS esilläolo
    'oas_esillaolokerta_1': [
        'milloin_oas_esillaolo_alkaa',
        'milloin_oas_esillaolo_paattyy',
        'oas_esillaolo_aineiston_maaraaika',
    ],
    'oas_esillaolokerta_2': [
        'milloin_oas_esillaolo_alkaa_2',
        'milloin_oas_esillaolo_paattyy_2',
        'oas_esillaolo_aineiston_maaraaika_2',
    ],
    'oas_esillaolokerta_3': [
        'milloin_oas_esillaolo_alkaa_3',
        'milloin_oas_esillaolo_paattyy_3',
        'oas_esillaolo_aineiston_maaraaika_3',
    ],
    # Luonnos esilläolo
    'luonnos_esillaolokerta_1': [
        'milloin_luonnos_esillaolo_alkaa',
        'milloin_luonnos_esillaolo_paattyy',
        'kaavaluonnos_esillaolo_aineiston_maaraaika',
    ],
    'luonnos_esillaolokerta_2': [
        'milloin_luonnos_esillaolo_alkaa_2',
        'milloin_luonnos_esillaolo_paattyy_2',
        'kaavaluonnos_esillaolo_aineiston_maaraaika_2',
    ],
    'luonnos_esillaolokerta_3': [
        'milloin_luonnos_esillaolo_alkaa_3',
        'milloin_luonnos_esillaolo_paattyy_3',
        'kaavaluonnos_esillaolo_aineiston_maaraaika_3',
    ],
    # Luonnos lautakunta
    'luonnos_lautakuntakerta_1': [
        'milloin_kaavaluonnos_lautakunnassa',
        'kaavaluonnos_kylk_aineiston_maaraaika',
    ],
    'luonnos_lautakuntakerta_2': [
        'milloin_kaavaluonnos_lautakunnassa_2',
        'kaavaluonnos_kylk_aineiston_maaraaika_2',
    ],
    'luonnos_lautakuntakerta_3': [
        'milloin_kaavaluonnos_lautakunnassa_3',
        'kaavaluonnos_kylk_aineiston_maaraaika_3',
    ],
    'luonnos_lautakuntakerta_4': [
        'milloin_kaavaluonnos_lautakunnassa_4',
        'kaavaluonnos_kylk_aineiston_maaraaika_4',
    ],
    # Ehdotus nähtävilläolo
    'ehdotus_nahtavillaolokerta_1': [
        'milloin_ehdotuksen_nahtavilla_alkaa',
        'milloin_ehdotuksen_nahtavilla_paattyy',
        'ehdotus_nahtaville_aineiston_maaraaika',
    ],
    'ehdotus_nahtavillaolokerta_2': [
        'milloin_ehdotuksen_nahtavilla_alkaa_2',
        'milloin_ehdotuksen_nahtavilla_paattyy_2',
        'ehdotus_nahtaville_aineiston_maaraaika_2',
    ],
    'ehdotus_nahtavillaolokerta_3': [
        'milloin_ehdotuksen_nahtavilla_alkaa_3',
        'milloin_ehdotuksen_nahtavilla_paattyy_3',
        'ehdotus_nahtaville_aineiston_maaraaika_3',
    ],
    'ehdotus_nahtavillaolokerta_4': [
        'milloin_ehdotuksen_nahtavilla_alkaa_4',
        'milloin_ehdotuksen_nahtavilla_paattyy_4',
        'ehdotus_nahtaville_aineiston_maaraaika_4',
    ],
    # Ehdotus lautakunta
    'ehdotus_lautakuntakerta_1': [
        'milloin_kaavaehdotus_lautakunnassa',
        'ehdotus_lautakunta_aineiston_maaraaika',
    ],
    'ehdotus_lautakuntakerta_2': [
        'milloin_kaavaehdotus_lautakunnassa_2',
        'ehdotus_lautakunta_aineiston_maaraaika_2',
    ],
    'ehdotus_lautakuntakerta_3': [
        'milloin_kaavaehdotus_lautakunnassa_3',
        'ehdotus_lautakunta_aineiston_maaraaika_3',
    ],
    'ehdotus_lautakuntakerta_4': [
        'milloin_kaavaehdotus_lautakunnassa_4',
        'ehdotus_lautakunta_aineiston_maaraaika_4',
    ],
    # Tarkistettu ehdotus lautakunta
    'tarkistettu_ehdotus_lautakuntakerta_1': [
        'milloin_tarkistettu_ehdotus_lautakunnassa',
        'tarkistettu_ehdotus_kylk_aineiston_maaraaika',
    ],
    'tarkistettu_ehdotus_lautakuntakerta_2': [
        'milloin_tarkistettu_ehdotus_lautakunnassa_2',
        'tarkistettu_ehdotus_kylk_aineiston_maaraaika_2',
    ],
    'tarkistettu_ehdotus_lautakuntakerta_3': [
        'milloin_tarkistettu_ehdotus_lautakunnassa_3',
        'tarkistettu_ehdotus_kylk_aineiston_maaraaika_3',
    ],
    'tarkistettu_ehdotus_lautakuntakerta_4': [
        'milloin_tarkistettu_ehdotus_lautakunnassa_4',
        'tarkistettu_ehdotus_kylk_aineiston_maaraaika_4',
    ],
}


def find_stale_deadline_fields(attribute_data):
    """
    Find stale deadline date fields in project attribute data.
    
    A date field is considered stale when:
    1. The associated deadline group's visibility bool is False
    2. But the date field still has a value
    
    Args:
        attribute_data (dict): The project's attribute_data dictionary
        
    Returns:
        list: List of tuples (deadline_group, vis_bool_name, stale_fields_list)
              where stale_fields_list is a list of dicts with 'field' and 'value' keys
    """
    stale_data = []
    attr_data = attribute_data or {}

    for deadline_group, vis_bool_name in VIS_BOOL_MAP.items():
        # Skip groups without visibility bools (kaynnistys, hyvaksyminen, voimaantulo)
        if vis_bool_name is None:
            continue

        # Get the visibility bool value
        vis_bool_value = attr_data.get(vis_bool_name)

        # Only check if vis_bool is explicitly False
        if vis_bool_value is not False:
            continue

        # Get date fields for this group
        date_fields = DEADLINE_GROUP_DATE_FIELDS.get(deadline_group, [])
        
        # Check for stale dates
        stale_fields = []
        for field in date_fields:
            value = attr_data.get(field)
            if value is not None:
                stale_fields.append({
                    'field': field,
                    'value': value,
                })

        if stale_fields:
            stale_data.append((deadline_group, vis_bool_name, stale_fields))

    return stale_data


def clean_stale_deadline_fields(attribute_data):
    """
    Remove stale deadline date fields from attribute_data.
    
    This function should be called during project save to prevent stale data
    from being persisted when a deadline group is disabled.
    
    KAAV-3492: When a visibility bool is set to False, we should automatically
    clear the associated deadline date fields to prevent stale data issues.
    
    Args:
        attribute_data (dict): The project's attribute_data dictionary (will be modified in-place)
        
    Returns:
        int: Number of fields that were cleared
    """
    if not isinstance(attribute_data, dict):
        return 0
    
    cleared_count = 0
    
    for deadline_group, vis_bool_name in VIS_BOOL_MAP.items():
        # Skip groups without visibility bools
        if vis_bool_name is None:
            continue
        
        # Only clean if vis_bool is explicitly False
        vis_bool_value = attribute_data.get(vis_bool_name)
        if vis_bool_value is not False:
            continue
        
        # Get date fields for this group
        date_fields = DEADLINE_GROUP_DATE_FIELDS.get(deadline_group, [])
        
        # Clear stale date fields
        for field in date_fields:
            if field in attribute_data and attribute_data[field] is not None:
                del attribute_data[field]
                cleared_count += 1
    
    return cleared_count
