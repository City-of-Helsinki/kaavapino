from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema

from users.models import User

import logging

logger = logging.getLogger(__name__)


class Ping(APIView):
    permission_classes = []  # Enable ping request without authentication

    @extend_schema(
        responses={200: OpenApiTypes.STR}
    )
    def get(self, __):
        return Response("pong")


class Status(APIView):
    permission_classes = []  # Enable status request without authentication

    @extend_schema(
        responses={
            200: OpenApiTypes.STR,
            503: OpenApiTypes.STR
        }
    )
    def get(self, __):
        try:
            User.objects.count()
            return Response("Kaavapino ok")
        except Exception as exc:
            logger.error("Exception in Status request", exc)
            return Response("Kaavapino not ok", status=status.HTTP_503_SERVICE_UNAVAILABLE)
