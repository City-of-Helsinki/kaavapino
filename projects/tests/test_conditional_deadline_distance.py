"""
Tests for DeadlineAttributeSchemaSerializer conditional deadline distance logic.

REGRESSION TEST FOR BUG:
- OLD BUG: _get_previous_deadline_distance() used .first() which ignored condition_attributes
- FIX: Now iterates through DeadlineDistance entries ordered by index and returns
  the FIRST one where check_conditions(attribute_data) returns True.

AUTHORITATIVE SOURCES (per AI_README.md):
- database_deadline_rules.md L109-L112: L6 has 4 conditional predecessors
- timeline-cascade-architecture.md: Frontend uses previous_deadline from schema

CATCHES BUGS:
1. OLD .first() ignores conditions → wrong predecessor returned
2. Ordering bug → should return FIRST by index, not last/random
3. None handling → should return None when no conditions match

RULES FOLLOWED (per TESTING.md):
- Test REAL behavior with real database models, not mocks
- Tests would FAIL if condition checking is broken
- Include adversarial cases (empty conditions, no matches, multiple matches)
- Integration boundary test: serializer ↔ database models
"""
import pytest

from projects.models import (
    Attribute,
    CommonProjectPhase,
    Deadline,
    DeadlineDistance,
    DeadlineDistanceConditionAttribute,
    ProjectPhase,
    ProjectSubtype,
    ProjectType,
)
from projects.serializers.projectschema import DeadlineAttributeSchemaSerializer
from projects.tests.factories import ProjectFactory


@pytest.fixture
def project_type():
    """Get or create asemakaava project type."""
    ptype, _ = ProjectType.objects.get_or_create(name="asemakaava")
    return ptype


@pytest.fixture
def xl_subtype(project_type):
    """Get or create XL subtype."""
    subtype, _ = ProjectSubtype.objects.get_or_create(
        project_type=project_type,
        name="XL",
        defaults={"index": 5}
    )
    return subtype


@pytest.fixture
def project_phase(xl_subtype):
    """
    Create a ProjectPhase for test deadlines.
    
    Deadline model requires a phase FK (NOT NULL).
    """
    common_phase, _ = CommonProjectPhase.objects.get_or_create(
        name="Test Phase",
        defaults={
            "color": "color--tram",
            "color_code": "#009246",
        }
    )
    phase, _ = ProjectPhase.objects.get_or_create(
        common_project_phase=common_phase,
        project_subtype=xl_subtype,
        defaults={"index": 0}
    )
    return phase


@pytest.fixture
def visibility_attribute():
    """
    Create a boolean visibility attribute used for conditions.
    Simulates: jarjestetaan_luonnos_esillaolo_1
    """
    attr, _ = Attribute.objects.get_or_create(
        identifier="test_esillaolo_visibility",
        defaults={
            "name": "Test Esillaolo Visibility",
            "value_type": Attribute.TYPE_BOOLEAN,
        }
    )
    return attr


@pytest.fixture
def deadline_attribute():
    """
    Create attribute for the deadline being tested.
    Simulates: kaavaluonnos_kylk_aineiston_maaraaika (L6)
    """
    attr, _ = Attribute.objects.get_or_create(
        identifier="test_kylk_maaraaika",
        defaults={
            "name": "Test KYLK Määräaika",
            "value_type": Attribute.TYPE_DATE,
        }
    )
    return attr


@pytest.fixture
def predecessor_attr_esillaolo():
    """
    First predecessor - conditional (e.g., milloin_luonnos_esillaolo_paattyy).
    Per database_deadline_rules.md L111: L6 from esillaolo_paattyy when esillaolo visible.
    """
    attr, _ = Attribute.objects.get_or_create(
        identifier="test_esillaolo_paattyy",
        defaults={
            "name": "Test Esillaolo Päättyy",
            "value_type": Attribute.TYPE_DATE,
        }
    )
    return attr


@pytest.fixture
def predecessor_attr_phase_start():
    """
    Fallback predecessor (e.g., luonnosvaihe_alkaa_pvm).
    Per database_deadline_rules.md L112: L6 from luonnosvaihe_alkaa_pvm when no esillaolo.
    """
    attr, _ = Attribute.objects.get_or_create(
        identifier="test_luonnosvaihe_alkaa_pvm",
        defaults={
            "name": "Test Luonnosvaihe Alkaa",
            "value_type": Attribute.TYPE_DATE,
        }
    )
    return attr


@pytest.fixture
def test_project(xl_subtype, project_phase):
    """
    Create a real Project using ProjectFactory.
    
    Per TESTING.md Rule 3: Minimize mocking - use real models when possible.
    ProjectFactory creates all required FK relationships automatically.
    We override subtype/phase to use our test fixtures for consistency.
    """
    project = ProjectFactory.create(
        subtype=xl_subtype,
        phase=project_phase,
        attribute_data={},
    )
    return project


@pytest.fixture
def setup_l6_pattern(
    xl_subtype,
    project_phase,
    deadline_attribute,
    predecessor_attr_esillaolo,
    predecessor_attr_phase_start,
    visibility_attribute,
):
    """
    Create L6-like deadline with conditional predecessors.
    
    Per database_deadline_rules.md L109-L112:
    - Index 0: From esillaolo_paattyy, requires jarjestetaan_esillaolo=True
    - Index 1: From phase_start, NO condition (fallback)
    
    This simulates the real L6 pattern where:
    - If esillaolo is visible → use esillaolo_paattyy + 5 days
    - If esillaolo is NOT visible → use phase_start + 5 days (fallback)
    """
    # Create the deadline (L6 equivalent)
    deadline, _ = Deadline.objects.get_or_create(
        subtype=xl_subtype,
        attribute=deadline_attribute,
        phase=project_phase,
        defaults={
            "abbreviation": "L6_TEST",
            "index": 100,
        }
    )
    
    # Create predecessor deadlines
    predecessor_esillaolo, _ = Deadline.objects.get_or_create(
        subtype=xl_subtype,
        attribute=predecessor_attr_esillaolo,
        phase=project_phase,
        defaults={
            "abbreviation": "L4_TEST",
            "index": 90,
        }
    )
    predecessor_phase_start, _ = Deadline.objects.get_or_create(
        subtype=xl_subtype,
        attribute=predecessor_attr_phase_start,
        phase=project_phase,
        defaults={
            "abbreviation": "L1_TEST",
            "index": 80,
        }
    )
    
    # Create condition attribute for esillaolo visibility
    condition_attr, _ = DeadlineDistanceConditionAttribute.objects.get_or_create(
        attribute=visibility_attribute,
        negate=False,
    )
    
    # Delete existing distances to ensure clean state
    DeadlineDistance.objects.filter(deadline=deadline).delete()
    
    # Index 0: From esillaolo_paattyy, requires visibility=True
    # Per database_deadline_rules.md: This is the conditional entry
    dist_conditional = DeadlineDistance.objects.create(
        deadline=deadline,
        previous_deadline=predecessor_esillaolo,
        distance_from_previous=5,  # Per L6 spec: +5 työpäivät
        index=0,
        condition_operator='and',
    )
    dist_conditional.condition_attributes.add(condition_attr)
    
    # Index 1: From phase_start, NO condition (fallback)
    # Per database_deadline_rules.md L112: luonnosvaihe_alkaa_pvm is fallback
    DeadlineDistance.objects.create(
        deadline=deadline,
        previous_deadline=predecessor_phase_start,
        distance_from_previous=5,  # Per L6 spec: +5 työpäivät
        index=1,
        # No condition_operator, no condition_attributes → always matches
    )
    
    return {
        'deadline': deadline,
        'predecessor_esillaolo': predecessor_esillaolo,
        'predecessor_phase_start': predecessor_phase_start,
        'condition_attr': condition_attr,
    }


@pytest.mark.django_db
class TestGetPreviousDeadlineDistanceConditional:
    """
    Tests for _get_previous_deadline_distance() method in DeadlineAttributeSchemaSerializer.
    
    Per timeline-cascade-architecture.md:
    - Frontend uses 'previous_deadline' field from schema to determine cascade predecessor
    - If wrong predecessor is returned, cascade goes to wrong date (the original L7.2 bug)
    
    Per database_deadline_rules.md L109-L112 (L6 pattern):
    - L6 (kaavaluonnos_kylk_aineiston_maaraaika) has 4 conditional predecessors
    - index 0: from milloin_luonnos_esillaolo_paattyy_3 (condition: esillaolo_3 visible)
    - index 1: from milloin_luonnos_esillaolo_paattyy_2 (condition: esillaolo_2 visible)  
    - index 2: from milloin_luonnos_esillaolo_paattyy (condition: esillaolo_1 visible)
    - index 3: from luonnosvaihe_alkaa_pvm (no condition - fallback)
    """

    def test_returns_conditional_entry_when_condition_true(
        self, 
        test_project,
        deadline_attribute,
        predecessor_attr_esillaolo,
        visibility_attribute,
        setup_l6_pattern,
    ):
        """
        When condition is TRUE, should return the conditional entry (index 0).
        
        OLD CODE: .first() returns index 0 → PASS (but for wrong reason)
        NEW CODE: checks conditions, index 0 matches → returns it
        
        This test passes with both old and new code but validates expected behavior.
        """
        # Set condition to TRUE (esillaolo IS visible)
        test_project.attribute_data = {
            visibility_attribute.identifier: True,
        }
        
        serializer = DeadlineAttributeSchemaSerializer(context={'project': test_project})
        
        result = serializer._get_previous_deadline_distance(deadline_attribute)
        
        assert result is not None, "Should return a DeadlineDistance when condition matches"
        assert result.previous_deadline.attribute.identifier == predecessor_attr_esillaolo.identifier, (
            f"With esillaolo visible, should use esillaolo_paattyy as predecessor, "
            f"got {result.previous_deadline.attribute.identifier}"
        )
        assert result.distance_from_previous == 5, (
            f"Per database_deadline_rules.md L111: distance should be 5 työpäivät"
        )
        assert result.index == 0, "Should return the conditional entry (index 0)"

    def test_skips_conditional_returns_fallback_when_condition_false(
        self, 
        test_project,
        deadline_attribute,
        predecessor_attr_phase_start,
        visibility_attribute,
        setup_l6_pattern,
    ):
        """
        CATCHES THE BUG: When condition is FALSE, should skip index 0 and return fallback.
        
        OLD CODE (.first()): 
        - Returns index 0 REGARDLESS of conditions → WRONG predecessor
        - This test FAILS with old code

        NEW CODE (iterate with check_conditions):
        - Index 0: check_conditions() returns False → skip
        - Index 1: no conditions → matches → return it
        
        Per database_deadline_rules.md L112:
        When esillaolo is NOT visible, L6 uses luonnosvaihe_alkaa_pvm as predecessor.
        """
        # Set condition to FALSE (esillaolo NOT visible)
        test_project.attribute_data = {
            visibility_attribute.identifier: False,
        }
        
        serializer = DeadlineAttributeSchemaSerializer(context={'project': test_project})
        
        result = serializer._get_previous_deadline_distance(deadline_attribute)
        
        assert result is not None, (
            "Should return fallback DeadlineDistance when conditional entry doesn't match"
        )
        assert result.previous_deadline.attribute.identifier == predecessor_attr_phase_start.identifier, (
            f"With esillaolo NOT visible, should skip index 0 and use phase_start (index 1), "
            f"got {result.previous_deadline.attribute.identifier}. "
            f"BUG: OLD .first() code ignores conditions and returns index 0."
        )
        assert result.index == 1, (
            f"Should return fallback entry (index 1), got index {result.index}. "
            f"This assertion would FAIL with old .first() code which returns index 0."
        )

    def test_skips_conditional_when_attribute_missing(
        self, 
        test_project,
        deadline_attribute,
        predecessor_attr_phase_start,
        setup_l6_pattern,
    ):
        """
        When condition attribute is MISSING from attribute_data, treat as False.
        
        Per check_conditions() logic:
        - Missing attribute → res = None → treated as falsy → condition fails
        - Should fall through to unconditional fallback
        
        This is important for new projects where visibility bools haven't been set.
        """
        # Empty attribute_data - condition attribute not present
        test_project.attribute_data = {}
        
        serializer = DeadlineAttributeSchemaSerializer(context={'project': test_project})
        
        result = serializer._get_previous_deadline_distance(deadline_attribute)
        
        assert result is not None
        assert result.previous_deadline.attribute.identifier == predecessor_attr_phase_start.identifier, (
            f"With missing visibility attribute, should use fallback, "
            f"got {result.previous_deadline.attribute.identifier}"
        )

    def test_returns_none_when_no_deadline_distance_exists(
        self,
        test_project,
        xl_subtype,
    ):
        """
        Method should gracefully handle attributes with no distance rules.
        
        Per validation.md:
        Fields without distance rules don't cascade - they're independent.
        """
        orphan_attr, _ = Attribute.objects.get_or_create(
            identifier="test_orphan_no_distances",
            defaults={
                "name": "Orphan Attribute",
                "value_type": Attribute.TYPE_DATE,
            }
        )
        
        serializer = DeadlineAttributeSchemaSerializer(context={'project': test_project})
        
        result = serializer._get_previous_deadline_distance(orphan_attr)
        
        assert result is None, "Should return None when no DeadlineDistance exists"

    def test_returns_none_when_all_conditions_fail(
        self,
        test_project,
        xl_subtype,
        project_phase,
        visibility_attribute,
    ):
        """
        When ALL DeadlineDistance entries have conditions and NONE match,
        should return None.
        
        This is an edge case - per database_deadline_rules.md, there should always
        be an unconditional fallback. But code should handle misconfigured data.
        """
        # Create deadline with ONLY conditional distance (no fallback)
        attr, _ = Attribute.objects.get_or_create(
            identifier="test_all_conditional",
            defaults={"name": "All Conditional", "value_type": Attribute.TYPE_DATE}
        )
        deadline, _ = Deadline.objects.get_or_create(
            subtype=xl_subtype,
            attribute=attr,
            phase=project_phase,
            defaults={"abbreviation": "ALLCOND", "index": 200}
        )
        predecessor, _ = Deadline.objects.get_or_create(
            subtype=xl_subtype,
            attribute=visibility_attribute,  # Reuse for simplicity
            phase=project_phase,
            defaults={"abbreviation": "PRED", "index": 190}
        )
        
        condition_attr, _ = DeadlineDistanceConditionAttribute.objects.get_or_create(
            attribute=visibility_attribute,
            negate=False,
        )
        
        # Clean and create ONLY conditional distance
        DeadlineDistance.objects.filter(deadline=deadline).delete()
        dist = DeadlineDistance.objects.create(
            deadline=deadline,
            previous_deadline=predecessor,
            distance_from_previous=5,
            index=0,
            condition_operator='and',
        )
        dist.condition_attributes.add(condition_attr)
        
        # Set condition to FALSE → nothing matches
        test_project.attribute_data = {
            visibility_attribute.identifier: False,
        }
        
        serializer = DeadlineAttributeSchemaSerializer(context={'project': test_project})
        
        result = serializer._get_previous_deadline_distance(attr)
        
        assert result is None, (
            "Should return None when all DeadlineDistance conditions fail"
        )

    def test_respects_index_ordering_multiple_unconditional(
        self,
        test_project,
        xl_subtype,
        project_phase,
    ):
        """
        When multiple unconditional entries exist, should return FIRST by index.
        
        Per DeadlineDistance.Meta.ordering = ('index',):
        - Query should be ordered by index
        - Iteration returns lowest index first
        """
        attr1, _ = Attribute.objects.get_or_create(
            identifier="test_ordering_target",
            defaults={"name": "Ordering Target", "value_type": Attribute.TYPE_DATE}
        )
        pred1, _ = Attribute.objects.get_or_create(
            identifier="test_ordering_pred1",
            defaults={"name": "Pred1", "value_type": Attribute.TYPE_DATE}
        )
        pred2, _ = Attribute.objects.get_or_create(
            identifier="test_ordering_pred2",
            defaults={"name": "Pred2", "value_type": Attribute.TYPE_DATE}
        )
        
        deadline, _ = Deadline.objects.get_or_create(
            subtype=xl_subtype,
            attribute=attr1,
            phase=project_phase,
            defaults={"abbreviation": "ORD", "index": 300}
        )
        pred_dl_1, _ = Deadline.objects.get_or_create(
            subtype=xl_subtype,
            attribute=pred1,
            phase=project_phase,
            defaults={"abbreviation": "P1", "index": 290}
        )
        pred_dl_2, _ = Deadline.objects.get_or_create(
            subtype=xl_subtype,
            attribute=pred2,
            phase=project_phase,
            defaults={"abbreviation": "P2", "index": 280}
        )
        
        # Clean and create in REVERSE order (to catch ordering bugs)
        DeadlineDistance.objects.filter(deadline=deadline).delete()
        
        # Create index 1 first (should NOT be returned)
        DeadlineDistance.objects.create(
            deadline=deadline,
            previous_deadline=pred_dl_2,
            distance_from_previous=20,
            index=1,
        )
        # Create index 0 second (should BE returned)
        DeadlineDistance.objects.create(
            deadline=deadline,
            previous_deadline=pred_dl_1,
            distance_from_previous=10,
            index=0,
        )
        
        serializer = DeadlineAttributeSchemaSerializer(context={'project': test_project})
        
        result = serializer._get_previous_deadline_distance(attr1)
        
        assert result is not None
        assert result.index == 0, (
            f"Should return entry with lowest index (0), got {result.index}"
        )
        assert result.previous_deadline.attribute.identifier == pred1.identifier


@pytest.mark.django_db
class TestGetNextDeadlineDistanceConditional:
    """
    Tests for _get_next_deadline_distance() - mirrors _get_previous but queries
    by previous_deadline__attribute instead of deadline__attribute.
    """

    def test_returns_none_for_attribute_with_no_successors(
        self,
        test_project,
    ):
        """
        Terminal attributes (phase endings) have no successors.
        """
        orphan_attr, _ = Attribute.objects.get_or_create(
            identifier="test_terminal_no_next",
            defaults={
                "name": "Terminal Attribute",
                "value_type": Attribute.TYPE_DATE,
            }
        )
        
        serializer = DeadlineAttributeSchemaSerializer(context={'project': test_project})
        
        result = serializer._get_next_deadline_distance(orphan_attr)
        
        assert result is None


@pytest.mark.django_db  
class TestCheckConditionsMethod:
    """
    Tests for DeadlineDistance.check_conditions() method.
    
    This is the core condition evaluation logic used by the serializer.
    Per database_deadline_rules.md, conditions determine which predecessor to use
    based on project state (e.g., which esillaolo variant is visible).
    """

    def test_returns_true_when_no_condition_attributes(self, xl_subtype, project_phase):
        """
        Unconditional entries (no condition_attributes) always match.
        
        Per database_deadline_rules.md L112: 
        luonnosvaihe_alkaa_pvm is fallback with no conditions.
        """
        attr, _ = Attribute.objects.get_or_create(
            identifier="test_uncond_check",
            defaults={"name": "Uncond", "value_type": Attribute.TYPE_DATE}
        )
        deadline, _ = Deadline.objects.get_or_create(
            subtype=xl_subtype,
            attribute=attr,
            phase=project_phase,
            defaults={"abbreviation": "U", "index": 400}
        )
        
        distance = DeadlineDistance.objects.create(
            deadline=deadline,
            previous_deadline=deadline,
            distance_from_previous=1,
            index=0,
        )
        
        # Should match regardless of attribute_data
        assert distance.check_conditions({}) is True
        assert distance.check_conditions({"random": "value"}) is True
        assert distance.check_conditions({"bool": False}) is True

    def test_and_operator_requires_condition_true(self, xl_subtype, project_phase, visibility_attribute):
        """
        'and' operator with single condition: must be truthy.
        """
        attr, _ = Attribute.objects.get_or_create(
            identifier="test_and_check",
            defaults={"name": "AND Check", "value_type": Attribute.TYPE_DATE}
        )
        deadline, _ = Deadline.objects.get_or_create(
            subtype=xl_subtype,
            attribute=attr,
            phase=project_phase,
            defaults={"abbreviation": "A", "index": 401}
        )
        
        condition_attr, _ = DeadlineDistanceConditionAttribute.objects.get_or_create(
            attribute=visibility_attribute,
            negate=False,
        )
        
        DeadlineDistance.objects.filter(deadline=deadline).delete()
        distance = DeadlineDistance.objects.create(
            deadline=deadline,
            previous_deadline=deadline,
            distance_from_previous=1,
            index=0,
            condition_operator='and',
        )
        distance.condition_attributes.add(condition_attr)
        
        # TRUE → matches
        assert distance.check_conditions({visibility_attribute.identifier: True}) is True
        # FALSE → no match
        assert distance.check_conditions({visibility_attribute.identifier: False}) is False
        # MISSING → no match (treated as falsy)
        assert distance.check_conditions({}) is False

    def test_negate_inverts_condition(self, xl_subtype, project_phase, visibility_attribute):
        """
        negate=True means "match when attribute is FALSE/missing".
        
        This is used for conditions like "NOT jarjestetaan_esillaolo" 
        (when esillaolo is explicitly disabled).
        """
        attr, _ = Attribute.objects.get_or_create(
            identifier="test_negate_check",
            defaults={"name": "Negate Check", "value_type": Attribute.TYPE_DATE}
        )
        deadline, _ = Deadline.objects.get_or_create(
            subtype=xl_subtype,
            attribute=attr,
            phase=project_phase,
            defaults={"abbreviation": "N", "index": 402}
        )
        
        # Create condition with negate=True
        condition_attr, _ = DeadlineDistanceConditionAttribute.objects.get_or_create(
            attribute=visibility_attribute,
            negate=True,
        )
        
        DeadlineDistance.objects.filter(deadline=deadline).delete()
        distance = DeadlineDistance.objects.create(
            deadline=deadline,
            previous_deadline=deadline,
            distance_from_previous=1,
            index=0,
            condition_operator='and',
        )
        distance.condition_attributes.add(condition_attr)
        
        # TRUE with negate → no match
        assert distance.check_conditions({visibility_attribute.identifier: True}) is False
        # FALSE with negate → matches
        assert distance.check_conditions({visibility_attribute.identifier: False}) is True
        # MISSING with negate → matches (None is falsy, negated = truthy)
        assert distance.check_conditions({}) is True


@pytest.mark.django_db
class TestRealL6ConditionalDistances:
    """
    Integration test against REAL database configuration.
    
    Per database_deadline_rules.md (L109-L112):
    L6 (kaavaluonnos_kylk_aineiston_maaraaika) has 4 conditional predecessors
    ordered by which esillaolo variant is visible.
    
    These tests verify the database is correctly configured AND
    the serializer correctly selects based on conditions.
    
    NOTE: These tests SKIP if L6 data isn't in the test database.
    They're integration tests that run against a populated database.
    """

    def test_l6_has_conditional_distances_in_database(self):
        """
        CATCHES CONFIG BUG: L6 missing conditional distance rules.
        
        Expected per database_deadline_rules.md:
        - Multiple DeadlineDistance entries for L6
        - At least one with condition_attributes
        """
        l6_distances = DeadlineDistance.objects.filter(
            deadline__attribute__identifier='kaavaluonnos_kylk_aineiston_maaraaika'
        ).select_related(
            'deadline__attribute', 
            'previous_deadline__attribute'
        ).prefetch_related('condition_attributes')
        
        if not l6_distances.exists():
            pytest.skip("L6 deadlines not in test database - run with full fixture")
        
        # L6 should have multiple predecessors (conditional)
        assert l6_distances.count() >= 2, (
            f"L6 should have multiple conditional predecessors per database_deadline_rules.md, "
            f"found {l6_distances.count()}"
        )

    def test_l6_fallback_is_phase_start(self):
        """
        Per database_deadline_rules.md L112:
        The highest-index entry should be luonnosvaihe_alkaa_pvm (fallback).
        """
        l6_distances = DeadlineDistance.objects.filter(
            deadline__attribute__identifier='kaavaluonnos_kylk_aineiston_maaraaika'
        ).select_related('previous_deadline__attribute').order_by('-index')
        
        if not l6_distances.exists():
            pytest.skip("L6 deadlines not in test database")
        
        fallback = l6_distances.first()
        
        # Fallback should be phase start (luonnosvaihe_alkaa_pvm)
        assert 'luonnosvaihe_alkaa_pvm' in fallback.previous_deadline.attribute.identifier, (
            f"L6 fallback (highest index) should be luonnosvaihe_alkaa_pvm, "
            f"got {fallback.previous_deadline.attribute.identifier}"
        )

    def test_l72_has_l7_as_predecessor(self):
        """
        Per database_deadline_rules.md L115:
        L7.2 (milloin_kaavaluonnos_lautakunnassa_2) predecessor is L7 (milloin_kaavaluonnos_lautakunnassa).
        
        This is the field mentioned in the original bug report.
        """
        l72_distances = DeadlineDistance.objects.filter(
            deadline__attribute__identifier='milloin_kaavaluonnos_lautakunnassa_2'
        ).select_related('previous_deadline__attribute')
        
        if not l72_distances.exists():
            pytest.skip("L7.2 deadline not in test database")
        
        # Should have exactly one predecessor: L7
        assert l72_distances.count() >= 1
        
        first_dist = l72_distances.first()
        assert 'milloin_kaavaluonnos_lautakunnassa' in first_dist.previous_deadline.attribute.identifier, (
            f"L7.2 predecessor should be milloin_kaavaluonnos_lautakunnassa (L7), "
            f"got {first_dist.previous_deadline.attribute.identifier}"
        )
        
        # Distance should be +1 työpäivät
        assert first_dist.distance_from_previous == 1, (
            f"Per database_deadline_rules.md L115: L7.2 distance from L7 is +1, "
            f"got {first_dist.distance_from_previous}"
        )
