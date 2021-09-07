import pytest

from projects.importing import AttributeImporter
from projects.models import CommonProjectPhase


@pytest.mark.django_db()
def test_project_phases_are_created(f_project_type, f_project_subtype):
    ai = AttributeImporter()
    ai.project_type = f_project_type
    ai.create_phases(f_project_subtype)

    assert CommonProjectPhase.objects.all().count() == 6

    for i in range(1, 7):
        assert CommonProjectPhase.objects.filter(index=i).exists()
