from pytest_factoryboy import register

# Disable Flake8 checks here as having fixtures in their
# own file is a lot nicer for readability.
from users.tests.factories import UserFactory
from .fixtures import *  # noqa: F401,F403
from .factories import *  # noqa: F403

register(UserFactory)
register(AttributeFactory)
register(FieldSetAttributeFactory)
register(ProjectTypeFactory)
register(ProjectPhaseFactory)
register(ProjectPhaseSectionFactory)
register(ProjectPhaseSectionAttributeFactory)
register(ProjectFactory)
