from rest_framework import mixins
from rest_framework.viewsets import GenericViewSet

from sitecontent.models import FooterSection
from sitecontent.serializers import FooterSectionSerializer

class FooterSectionViewSet(mixins.ListModelMixin, GenericViewSet):
    queryset = FooterSection.objects.all().prefetch_related("links")
    serializer_class = FooterSectionSerializer
