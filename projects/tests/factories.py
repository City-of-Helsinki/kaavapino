import factory
from factory import fuzzy

from projects.models import (
    Attribute,
    CommonProjectPhase,
    FieldSetAttribute,
    Project,
    ProjectType,
    ProjectSubtype,
    ProjectPhase,
    ProjectPhaseSection,
    ProjectPhaseSectionAttribute,
    ProjectComment,
    Report,
    ReportFilter,
)
from users.tests.factories import UserFactory

__all__ = (
    "AttributeFactory",
    "CommonProjectPhaseFactory",
    "FieldSetAttributeFactory",
    "ProjectTypeFactory",
    "ProjectSubtypeFactory",
    "ProjectPhaseFactory",
    "ProjectPhaseSectionFactory",
    "ProjectPhaseSectionAttributeFactory",
    "ProjectFactory",
    "ReportFactory",
    "ReportFilterFactory",
)


class AttributeFactory(factory.django.DjangoModelFactory):
    name = fuzzy.FuzzyText(prefix="Attribute ", length=16)
    help_text = factory.Sequence(lambda n: f"Help for attribute {n}")
    value_type = Attribute.TYPE_SHORT_STRING
    identifier = fuzzy.FuzzyText(prefix="attribute", length=16)

    class Meta:
        model = Attribute


class FieldSetAttributeFactory(factory.django.DjangoModelFactory):
    attribute_source = factory.SubFactory(AttributeFactory)
    attribute_target = factory.SubFactory(AttributeFactory)

    class Meta:
        model = FieldSetAttribute


class ProjectTypeFactory(factory.django.DjangoModelFactory):
    name = "asemakaava"

    class Meta:
        model = ProjectType
        django_get_or_create = ("name",)


class ProjectSubtypeFactory(factory.django.DjangoModelFactory):
    project_type = factory.SubFactory(ProjectTypeFactory)
    name = factory.fuzzy.FuzzyChoice(["XS", "S", "M", "L", "XL"])
    index = factory.Sequence(int)

    class Meta:
        model = ProjectSubtype
        django_get_or_create = ("name", "project_type")


class CommonProjectPhaseFactory(factory.django.DjangoModelFactory):
    name = fuzzy.FuzzyText()

    class Meta:
        model = CommonProjectPhase


class ProjectPhaseFactory(factory.django.DjangoModelFactory):
    common_project_phase = factory.SubFactory(CommonProjectPhaseFactory)
    project_subtype = factory.SubFactory(ProjectSubtypeFactory)
    index = factory.Sequence(int)

    class Meta:
        model = ProjectPhase


class ProjectPhaseSectionFactory(factory.django.DjangoModelFactory):
    phase = factory.SubFactory(ProjectPhaseFactory)
    name = fuzzy.FuzzyText()
    index = factory.Sequence(int)

    class Meta:
        model = ProjectPhaseSection


class ProjectPhaseSectionAttributeFactory(factory.django.DjangoModelFactory):
    attribute = factory.SubFactory(AttributeFactory)
    section = factory.SubFactory(ProjectPhaseSectionFactory)
    index = factory.Sequence(int)

    class Meta:
        model = ProjectPhaseSectionAttribute


class ProjectFactory(factory.django.DjangoModelFactory):
    identifier = fuzzy.FuzzyText()
    name = factory.Faker("street_name")
    user = factory.SubFactory(UserFactory)
    subtype = factory.SubFactory(ProjectSubtypeFactory)
    phase = factory.SubFactory(ProjectPhaseFactory)
    public = True

    class Meta:
        model = Project


class CommentFactory(factory.django.DjangoModelFactory):
    content = factory.Faker("sentence")
    user = factory.SubFactory(UserFactory)
    project = factory.SubFactory(ProjectFactory)

    class Meta:
        model = ProjectComment


class ReportFactory(factory.django.DjangoModelFactory):
    project_type = factory.SubFactory(ProjectTypeFactory)
    name = fuzzy.FuzzyText()
    show_created_at = True

    class Meta:
        model = Report


class ReportFilterFactory(factory.django.DjangoModelFactory):
    name = fuzzy.FuzzyText()
    identifier = fuzzy.FuzzyText(prefix="attribute", length=16)
    type = "exact"

    class Meta:
        model = ReportFilter
