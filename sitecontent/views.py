from rest_framework import mixins, status
from rest_framework.response import Response
from rest_framework import serializers
from rest_framework.views import APIView
from rest_framework.viewsets import GenericViewSet

from drf_spectacular.utils import extend_schema, inline_serializer
from drf_spectacular.types import OpenApiTypes
from sitecontent.models import FooterSection, TargetFloorArea
from sitecontent.serializers import FooterSectionSerializer
from projects.models import CommonProjectPhase
from projects.serializers.project import CommonProjectPhaseSerializer

class FooterSectionViewSet(mixins.ListModelMixin, GenericViewSet):
    queryset = FooterSection.objects.all().prefetch_related("links")
    serializer_class = FooterSectionSerializer


class TargetFloorAreas(APIView):
    @extend_schema(
        responses=inline_serializer('TargetFloorAreas', fields={
            '[year]': serializers.IntegerField()
        })
    )
    def get(self, __):
        return Response({
            obj.year: obj.target
            for obj in TargetFloorArea.objects.order_by("year")
        }, status=status.HTTP_200_OK)


class Legend(APIView):
    @extend_schema(
        responses=inline_serializer('Legend', fields={'phases': CommonProjectPhaseSerializer(many=True)})
    )
    def get(self, __):
        return Response({
            "phases": CommonProjectPhaseSerializer(
                CommonProjectPhase.objects.all(),
                many=True,
            ).data
        })


class Ping(APIView):
    @extend_schema(
        responses={200: OpenApiTypes.STR}
    )
    def get(self, __):
        return Response("pong")
