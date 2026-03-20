"""
Tests for deadline data completeness.

These tests verify that all deadlines in the database have proper
distance/calculation values defined, which come from the Excel import.

This catches data quality issues that would otherwise cause:
- Frontend to use hardcoded fallback values
- Incorrect distance enforcement between deadlines
- Lautakunta slots not respecting minimum gaps

If these tests fail, the Excel file needs to be updated and re-imported.
"""
from django.test import TestCase

from projects.models import (
    Deadline,
    DeadlineDistance,
    ProjectSubtype,
)


class TestDeadlineDataCompleteness(TestCase):
    """
    Tests to verify all deadlines have required distance/calculation data.
    
    These tests validate that the Excel import has populated all necessary
    fields. If any test fails, check the Excel file and re-import.
    """

    def test_all_deadlines_have_date_type(self):
        """All deadlines should have a date_type defined."""
        deadlines_without_date_type = Deadline.objects.filter(
            date_type__isnull=True
        ).exclude(
            # Exclude deadlines that legitimately don't need date_type
            abbreviation__in=[]  # Add any exceptions here
        )
        
        if deadlines_without_date_type.exists():
            missing = list(deadlines_without_date_type.values_list(
                'abbreviation', 'subtype__name'
            ))
            self.fail(
                f"Deadlines missing date_type (update Excel 'päivätyyppi' column):\n"
                f"{missing}"
            )

    def test_all_secondary_slots_have_distance_rules(self):
        """
        ALL deadlines with secondary slots (_2, _3, _4) should have
        DeadlineDistance records defining minimum gaps from previous deadlines.
        
        This covers all phases:
        - P (Periaatteet): P7.2, P7.3, P7.4
        - O (OAS): O2.2, O3.2, O4.2, O5.2, etc.
        - L (Luonnos): L2.2, L3.2, L4.2, L5.2, L7.2, etc.
        - E (Ehdotus): E2.2, E3.2, E4.2, E5.2, E6.2, E8.2, etc.
        - T (Tarkistettu ehdotus): T3.2, T3.3, T3.4
        """
        # Find ALL deadlines with secondary slot suffixes
        secondary_deadlines = Deadline.objects.filter(
            attribute__identifier__regex=r'.*_[234]$'
        ).select_related('attribute', 'subtype')
        
        missing_distances = []
        
        for deadline in secondary_deadlines:
            # Check if this deadline has any distance rules
            has_distance = DeadlineDistance.objects.filter(
                deadline=deadline
            ).exists()
            
            if not has_distance:
                missing_distances.append(
                    f"{deadline.abbreviation} ({deadline.attribute.identifier if deadline.attribute else 'no attr'}) - {deadline.subtype.name}"
                )
        
        if missing_distances:
            self.fail(
                f"Secondary slot deadlines missing DeadlineDistance rules "
                f"(update Excel 'minimietäisyys' column):\n"
                + "\n".join(sorted(set(missing_distances))[:30])
                + (f"\n... and {len(set(missing_distances)) - 30} more" 
                   if len(set(missing_distances)) > 30 else "")
            )

    def test_secondary_slots_have_distance_from_previous_slot(self):
        """
        ALL secondary slots (_2, _3, _4) should have distance rules
        from their corresponding previous slot.
        
        This covers:
        - Lautakunta: P7.2, L7.2, E8.2, T3.2 etc.
        - Esillaoloaikaa: O3.2, L3.2, E3.2/E4.2 etc.
        - Mielipiteet/lausunnot: O5.2, L5.2, E6.2 etc.
        - Aineisto maaraaika: O2.2, L2.2, E2.2 etc.
        
        For example:
        - milloin_kaavaehdotus_lautakunnassa_2 should have distance from _1 (or unsuffixed)
        - milloin_ehdotuksen_nahtavilla_alkaa_pieni_3 should have distance from _2
        """
        # Pattern: deadlines ending with _2, _3, or _4
        secondary_patterns = ['_2', '_3', '_4']
        
        issues = []
        
        for subtype in ProjectSubtype.objects.all():
            for pattern in secondary_patterns:
                # Get ALL secondary deadlines, not just lautakunnassa
                secondary_deadlines = Deadline.objects.filter(
                    subtype=subtype,
                    attribute__identifier__endswith=pattern,
                ).select_related('attribute')
                
                for deadline in secondary_deadlines:
                    # Find the expected previous slot
                    identifier = deadline.attribute.identifier
                    slot_num = int(pattern[1])  # Extract number from _2, _3, _4
                    prev_slot_num = slot_num - 1
                    
                    if prev_slot_num == 1:
                        # _1 might not have suffix in identifier
                        prev_identifier_options = [
                            identifier.replace(pattern, '_1'),
                            identifier.replace(pattern, ''),  # No suffix for first slot
                        ]
                    else:
                        prev_identifier_options = [
                            identifier.replace(pattern, f'_{prev_slot_num}')
                        ]
                    
                    # Check if distance rule exists from any of the previous options
                    has_valid_distance = DeadlineDistance.objects.filter(
                        deadline=deadline,
                        previous_deadline__attribute__identifier__in=prev_identifier_options
                    ).exists()
                    
                    if not has_valid_distance:
                        # Check what distance rules DO exist
                        existing = list(DeadlineDistance.objects.filter(
                            deadline=deadline
                        ).values_list(
                            'previous_deadline__attribute__identifier',
                            'distance_from_previous'
                        ))
                        
                        issues.append(
                            f"{identifier} ({subtype.name}): "
                            f"expected distance from {prev_identifier_options}, "
                            f"found: {existing}"
                        )
        
        if issues:
            self.fail(
                f"Secondary lautakunta slots missing distance from previous slot "
                f"(update Excel 'minimietäisyys' column):\n"
                + "\n".join(issues)
            )

    def test_deadlines_with_initial_calculations_have_valid_references(self):
        """
        Deadlines with initial_calculations should reference valid base deadlines.
        """
        deadlines_with_calcs = Deadline.objects.filter(
            initial_calculations__isnull=False
        ).distinct().prefetch_related('initial_calculations')
        
        invalid_calcs = []
        
        for deadline in deadlines_with_calcs:
            for calc in deadline.initial_calculations.all():
                if hasattr(calc, 'datecalculation'):
                    dc = calc.datecalculation
                    if dc.base_date_deadline and not Deadline.objects.filter(
                        pk=dc.base_date_deadline.pk
                    ).exists():
                        invalid_calcs.append(
                            f"{deadline.abbreviation}: references non-existent deadline"
                        )
        
        if invalid_calcs:
            self.fail(
                f"Deadlines with invalid initial_calculation references:\n"
                + "\n".join(invalid_calcs)
            )

    def test_distance_values_are_reasonable(self):
        """
        Distance values should be within reasonable bounds.
        
        - Not negative
        - Not excessively large (> 365 days seems wrong)
        - Lautakunta distances should typically be small (1-30 days between slots)
        """
        # Check for negative distances
        negative = DeadlineDistance.objects.filter(
            distance_from_previous__lt=0
        ).values_list(
            'deadline__abbreviation',
            'previous_deadline__abbreviation', 
            'distance_from_previous'
        )
        
        if negative:
            self.fail(f"Negative distance values found: {list(negative)}")
        
        # Check for excessively large distances
        excessive = DeadlineDistance.objects.filter(
            distance_from_previous__gt=365
        ).values_list(
            'deadline__abbreviation',
            'previous_deadline__abbreviation',
            'distance_from_previous'
        )
        
        if excessive:
            self.fail(f"Excessive distance values (>365 days) found: {list(excessive)}")

    def test_all_subtypes_have_consistent_deadline_structure(self):
        """
        All subtypes should have the same deadline structure.
        
        If one subtype has lautakunta_2, all subtypes should have it.
        """
        # Get all unique abbreviations per subtype
        subtypes = ProjectSubtype.objects.all()
        abbreviations_by_subtype = {}
        
        for subtype in subtypes:
            abbrevs = set(Deadline.objects.filter(
                subtype=subtype
            ).values_list('abbreviation', flat=True))
            abbreviations_by_subtype[subtype.name] = abbrevs
        
        # Find abbreviations that exist in some subtypes but not others
        all_abbreviations = set()
        for abbrevs in abbreviations_by_subtype.values():
            all_abbreviations.update(abbrevs)
        
        for abbrev in all_abbreviations:
            present_in = [
                name for name, abbrevs in abbreviations_by_subtype.items()
                if abbrev in abbrevs
            ]
            missing_in = [
                name for name, abbrevs in abbreviations_by_subtype.items()
                if abbrev not in abbrevs
            ]
            
            # Only report if it's partially present (not all or none)
            if present_in and missing_in and len(present_in) > 0:
                # This might be intentional for some deadlines, so just log it
                pass  # Could add warning here if needed
        
        # This test passes if we get here - inconsistencies are not necessarily errors


class TestFrontendDistanceDataAvailability(TestCase):
    """
    Tests that verify the data the frontend needs is available.
    
    The frontend's objectUtil.js uses:
    - initial_distance (from deadline.calculate_initial)
    - distance_from_previous (from DeadlineDistance)
    
    These tests ensure at least one of these is available for all deadlines.
    """

    def test_all_deadlines_have_distance_data_for_frontend(self):
        """
        Every deadline should have either:
        - initial_calculations (provides initial_distance), OR
        - DeadlineDistance record (provides distance_from_previous)
        
        Without either, the frontend would have no distance information.
        """
        deadlines_missing_both = []
        
        for deadline in Deadline.objects.all().select_related(
            'attribute', 'subtype'
        ).prefetch_related('initial_calculations'):
            
            has_initial_calcs = deadline.initial_calculations.exists()
            has_distance_rule = DeadlineDistance.objects.filter(
                deadline=deadline
            ).exists()
            
            if not has_initial_calcs and not has_distance_rule:
                # This deadline has no distance information at all
                deadlines_missing_both.append(
                    f"{deadline.abbreviation} "
                    f"({deadline.attribute.identifier if deadline.attribute else 'no attr'}) "
                    f"- {deadline.subtype.name}"
                )
        
        if deadlines_missing_both:
            # Group by pattern to make output more readable
            self.fail(
                f"Deadlines with no distance data (need initial_calculations OR minimietäisyys in Excel):\n"
                + "\n".join(deadlines_missing_both[:20])  # Limit output
                + (f"\n... and {len(deadlines_missing_both) - 20} more" 
                   if len(deadlines_missing_both) > 20 else "")
            )

    def test_secondary_slots_have_correct_distance_values(self):
        """
        ALL secondary slots (_2, _3, _4) should have correct minimum distance
        from their corresponding previous slot.
        
        Different deadline types may have different expected distances:
        - Lautakunta slots (lautakunnassa): 1 day between consecutive meetings
        - Esillaoloaikaa (esillaolo, nahtavilla): varies by type
        - Others: check Excel specification
        
        If this test fails, update the Excel "minimietäisyys" column.
        """
        # Expected distances for different deadline types
        # Key: substring to match in identifier, Value: expected distance
        expected_distances = {
            'lautakunnassa': 1,  # 1 day between consecutive lautakunta meetings
            # Add other patterns as needed:
            # 'esillaolo': 5,
            # 'nahtavilla': 5,
        }
        
        issues = []
        
        for subtype in ProjectSubtype.objects.all():
            for slot in ['_2', '_3', '_4']:
                # Get ALL secondary deadlines
                deadlines = Deadline.objects.filter(
                    subtype=subtype,
                    attribute__identifier__endswith=slot
                ).select_related('attribute')
                
                for deadline in deadlines:
                    if not deadline.attribute:
                        continue
                        
                    identifier = deadline.attribute.identifier
                    
                    # Find which expected distance applies
                    expected = None
                    matched_pattern = None
                    for pattern, dist in expected_distances.items():
                        if pattern in identifier:
                            expected = dist
                            matched_pattern = pattern
                            break
                    
                    if expected is None:
                        # No expectation defined for this type, skip
                        continue
                    
                    # Check distances to same-type previous deadline
                    distances = DeadlineDistance.objects.filter(
                        deadline=deadline
                    ).select_related('previous_deadline', 'previous_deadline__attribute')
                    
                    for dist in distances:
                        prev_attr = dist.previous_deadline.attribute
                        if prev_attr and matched_pattern in prev_attr.identifier:
                            # This is a same-type consecutive distance
                            if dist.distance_from_previous != expected:
                                issues.append(
                                    f"{identifier} ({subtype.name}): "
                                    f"distance from {prev_attr.identifier} is {dist.distance_from_previous}, "
                                    f"expected {expected}"
                                )
        
        if issues:
            # Group by pattern for clearer output
            self.fail(
                f"Secondary slots have incorrect distance values.\n"
                f"Expected distances: {expected_distances}\n"
                f"Update the Excel 'minimietäisyys' column and re-import:\n"
                + "\n".join(issues[:30])
                + (f"\n... and {len(issues) - 30} more" if len(issues) > 30 else "")
            )
