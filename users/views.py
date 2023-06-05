import requests

from django.conf import settings
from django.contrib.auth import get_user_model
from django.http import Http404
from drf_spectacular.utils import extend_schema, OpenApiParameter
from drf_spectacular.types import OpenApiTypes
from rest_framework import mixins, status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.viewsets import GenericViewSet

from users.serializers import (
    PersonnelSerializer,
    UserSerializer,
)
from users.helpers import get_graph_api_access_token


class UserViewSet(mixins.RetrieveModelMixin, mixins.ListModelMixin, GenericViewSet):
    queryset = get_user_model().objects.filter(hide_from_ui=False).prefetch_related("groups", "additional_groups")
    serializer_class = UserSerializer
    lookup_field = "uuid"


class PersonnelList(APIView):
    @extend_schema(
        responses=PersonnelSerializer(many=True),
        parameters=[
            OpenApiParameter("search", OpenApiTypes.STR, OpenApiParameter.QUERY),
            OpenApiParameter("company_name", OpenApiTypes.STR, OpenApiParameter.QUERY),
        ],
    )
    def get(self, request):
        token = get_graph_api_access_token()
        if not token:
            return Response(
                "Cannot get access token",
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        search = request.query_params.get("search")
        company_name = request.query_params.get("company_name", None)

        url = \
            f"{settings.GRAPH_API_BASE_URL}/v1.0/users/" + \
            f"?$search=\"displayName:{search}\"" + \
            "&$filter=endsWith(mail, \'@hel.fi\')" + \
            (f" and companyName eq \'{company_name}\'" if company_name
             else " and companyName in('KYMP', 'KUVA', 'KASKO', 'KEHA')") + \
            "&$select=id,givenName,surname,mobilePhone,businessPhones,companyName,mail,jobTitle,officeLocation"

        response = requests.get(
            url,
            headers={
                "Authorization": f"Bearer {token}",
                "consistencyLevel": "eventual",
            },
        )
        if response:
            return Response(PersonnelSerializer(
                response.json().get("value", []),
                many=True,
            ).data)
        elif response.status_code == 401:
            return Response(
                "Kaavapino server not authorized to access users",
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
        else:
            return Response("Bad request", status=status.HTTP_400_BAD_REQUEST)


class PersonnelDetail(APIView):
    @extend_schema(
        responses=PersonnelSerializer(many=False),
    )
    def get(self, __, pk):
        token = get_graph_api_access_token()
        if not token:
            return Response(
                "Cannot get access token",
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        response = requests.get(
            f"{settings.GRAPH_API_BASE_URL}/v1.0/users/{pk}"
            f"?$select=id,givenName,surname,mobilePhone,businessPhones,companyName,mail,jobTitle,officeLocation",
            headers={
                "Authorization": f"Bearer {token}",
            },
        )

        if response:
            return Response(PersonnelSerializer(response.json(), many=False).data)
        elif response.status_code == 404:
            raise Http404
        elif response.status_code == 401:
            return Response(
                "Kaavapino server not authorized to access users",
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
        else:
            return Response("Bad request", status=status.HTTP_400_BAD_REQUEST)
