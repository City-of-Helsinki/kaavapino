import requests

from django.conf import settings
from django.core.cache import cache


def get_graph_api_access_token() -> str:
    token: str = cache.get("GRAPH_API_token")
    if not token:
        response = requests.post(
            f"{settings.GRAPH_API_LOGIN_BASE_URL}/{settings.GRAPH_API_TENANT_ID}/oauth2/v2.0/token",
            data={
                "client_id": settings.GRAPH_API_APPLICATION_ID,
                "scope": "https://graph.microsoft.com/.default",
                "client_secret": settings.GRAPH_API_CLIENT_SECRET,
                "grant_type": "client_credentials",
            },
        )
        if response:
            response = response.json()
            token = response.get("access_token")
            expires_in = response.get("expires_in")

            # Expire cache a moment before the token expires
            cache.set("GRAPH_API_token", token, expires_in-30)

    return token
