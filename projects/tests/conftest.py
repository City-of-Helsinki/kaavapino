# flake8: noqa
# Disable Flake8 checks here as having fixtures and factories in their
# own files is a lot nicer for readability.
from pytest_factoryboy import register

from projects.tests.factories import CommentFactory
from users.tests.factories import UserFactory
from .fixtures import *
from .factories import *

register(UserFactory)
register(AttributeFactory)
register(CommonProjectPhaseFactory)
register(FieldSetAttributeFactory)
register(ProjectTypeFactory)
register(ProjectSubtypeFactory)
register(ProjectPhaseFactory)
register(ProjectPhaseSectionFactory)
register(ProjectPhaseSectionAttributeFactory)
register(ProjectFactory)
register(CommentFactory)
register(ReportFactory)
register(ReportFilterFactory)
