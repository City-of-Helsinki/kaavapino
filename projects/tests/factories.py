import factory
from factory import fuzzy

from projects.models import (
    Attribute,
    FieldSetAttribute,
    Project,
    ProjectType,
    ProjectPhase,
    ProjectPhaseSection,
    ProjectPhaseSectionAttribute,
)
from users.tests.factories import UserFactory

__all__ = (
    "AttributeFactory",
    "FieldSetAttributeFactory",
    "ProjectTypeFactory",
    "ProjectPhaseFactory",
    "ProjectPhaseSectionFactory",
    "ProjectPhaseSectionAttributeFactory",
    "ProjectFactory",
)


class AttributeFactory(factory.DjangoModelFactory):
    name = fuzzy.FuzzyText(prefix="Attribute ", length=16)
    help_text = factory.Sequence(lambda n: f"Help for attribute {n}")
    value_type = Attribute.TYPE_SHORT_STRING
    identifier = fuzzy.FuzzyText(prefix="attribute", length=16)

    class Meta:
        model = Attribute


class FieldSetAttributeFactory(factory.DjangoModelFactory):
    attribute_source = factory.SubFactory(AttributeFactory)
    attribute_target = factory.SubFactory(AttributeFactory)
    index = factory.Sequence(int)

    class Meta:
        model = FieldSetAttribute


class ProjectTypeFactory(factory.DjangoModelFactory):
    name = "asemakaava"

    class Meta:
        model = ProjectType
        django_get_or_create = ("name",)


class ProjectPhaseFactory(factory.DjangoModelFactory):
    project_type = factory.SubFactory(ProjectTypeFactory)
    name = fuzzy.FuzzyText()
    index = factory.Sequence(int)

    class Meta:
        model = ProjectPhase


class ProjectPhaseSectionFactory(factory.DjangoModelFactory):
    phase = factory.SubFactory(ProjectPhaseFactory)
    name = fuzzy.FuzzyText()
    index = factory.Sequence(int)

    class Meta:
        model = ProjectPhaseSection


class ProjectPhaseSectionAttributeFactory(factory.DjangoModelFactory):
    attribute = factory.SubFactory(AttributeFactory)
    section = factory.SubFactory(ProjectPhaseSectionFactory)
    index = factory.Sequence(int)

    class Meta:
        model = ProjectPhaseSectionAttribute


class ProjectFactory(factory.DjangoModelFactory):
    identifier = fuzzy.FuzzyText()
    name = factory.Faker("street_name")
    user = factory.SubFactory(UserFactory)
    type = factory.SubFactory(ProjectTypeFactory)
    phase = factory.SubFactory(ProjectPhaseFactory)

    class Meta:
        model = Project
