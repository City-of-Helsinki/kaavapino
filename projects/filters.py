import django_filters

from projects.models import Project


class ProjectFilter(django_filters.FilterSet):
    class Meta:
        model = Project
        fields = {
            "id": ["exact", "in"],
            "identifier": ["exact", "in"],
            "user__uuid": ["exact", "in"],
            "created_at": ["lt", "gt", "date__exact", "date__lte", "date__gte"],
            "modified_at": ["lt", "gt", "date__exact", "date__lte", "date__gte"],
            "name": ["exact", "iexact", "icontains"],
            "subtype__name": ["exact", "iexact"],
            "phase__index": ["exact", "in"],
            "phase__name": ["exact", "iexact"],
        }
