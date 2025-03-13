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
    queryset = get_user_model().objects.filter(hide_from_ui=False, username__startswith="u-").prefetch_related("groups", "additional_groups")
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

        search = request.query_params.get("search", "").strip()
        company_name = request.query_params.get("company_name", None)
        #Initialize base URL
        base_url = f"{settings.GRAPH_API_BASE_URL}/v1.0/users/"
        query_params = []

        #Only apply `$search` if a valid search term is provided
        if search and search != "*":
            query_params.append(f'$search="displayName:{search}"')

        #Correctly format `$filter` conditions
        filter_conditions = ["endsWith(mail, '@hel.fi')"]

        if company_name:
            filter_conditions.append(f"companyName eq '{company_name}'")
        else:
            company_filter = " or ".join(
                [f"companyName eq '{c}'" for c in ['KYMP', 'KUVA', 'KASKO', 'KEHA', 'KANSLIA']]
            )
            filter_conditions.append(f"({company_filter})")

        if filter_conditions:
            query_params.append(f"$filter=({' and '.join(filter_conditions)})")

        #Add `$count=true` to enable `endsWith()`
        query_params.append("$count=true")
        #Select required fields
        query_params.append(
            "$select=id,givenName,surname,mobilePhone,businessPhones,companyName,mail,jobTitle,officeLocation"
        )
        #Ensure URL is properly constructed
        url = base_url + ("?" + "&".join(query_params) if query_params else "")

        response = requests.get(
            url,
            headers={
                "Authorization": f"Bearer {token}",
                "consistencyLevel": "eventual",  # ✅ Required for `endsWith`
            },
        )

        if response.status_code == 200:
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
            return Response(f"Bad request: {response.text}", status=status.HTTP_400_BAD_REQUEST)


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
