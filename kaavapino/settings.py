"""
Django settings for kaavapino project.

For more information on this file, see
https://docs.djangoproject.com/en/2.1/topics/settings/

For the full list of settings and their values, see
https://docs.djangoproject.com/en/2.1/ref/settings/
"""

import os
import sys

import environ
import sentry_sdk
from sentry_sdk.integrations.django import DjangoIntegration


project_root = environ.Path(__file__) - 2

env = environ.Env(
    DEBUG=(bool, True),
    SECRET_KEY=(str, ""),
    ALLOWED_HOSTS=(list, []),
    DATABASE_URL=(str, "postgis://kaavapino:kaavapino@localhost/kaavapino"),
    CACHE_URL=(str, "locmemcache://"),
    EMAIL_URL=(str, "consolemail://"),
    MEDIA_ROOT=(environ.Path, project_root("media")),
    STATIC_ROOT=(environ.Path, project_root("static")),
    MEDIA_URL=(str, "/media/"),
    STATIC_URL=(str, "/static/"),
    DOCUMENT_EDIT_URL_FORMAT=(str, ""),
    TOKEN_AUTH_ACCEPTED_AUDIENCE=(str, "AUDIENCE_UNSET"),
    TOKEN_AUTH_ACCEPTED_SCOPE_PREFIX=(str, "SCOPE_PREFIX_UNSET"),
    TOKEN_AUTH_AUTHSERVER_URL=(str, "ISSUER_UNSET"),
    TOKEN_AUTH_REQUIRE_SCOPE_PREFIX=(bool, True),
    NGINX_X_ACCEL=(bool, False),
    USE_X_FORWARDED_HOST=(bool, False),
    SENTRY_DSN=(str, ""),
    SENTRY_ENVIRONMENT=(str, "development"),
    CSRF_COOKIE_DOMAIN=(str, ""),
    CSRF_TRUSTED_ORIGINS=(list, []),
    SOCIAL_AUTH_TUNNISTAMO_SECRET=(str, "SECRET_UNSET"),
    SOCIAL_AUTH_TUNNISTAMO_KEY=(str, "KEY_UNSET"),
    SOCIAL_AUTH_TUNNISTAMO_OIDC_ENDPOINT=(str, "OIDC_ENDPOINT_UNSET"),
    KAAVOITUS_API_BASE_URL=(str, ""),
    KAAVOITUS_API_AUTH_TOKEN=(str, ""),
    GRAPH_API_LOGIN_BASE_URL=(str, ""),
    GRAPH_API_BASE_URL=(str, ""),
    GRAPH_API_APPLICATION_ID=(str, ""),
    GRAPH_API_TENANT_ID=(str, ""),
    GRAPH_API_CLIENT_SECRET=(str, ""),
)

if env('SENTRY_DSN'):
    sentry_sdk.init(
        dsn=env('SENTRY_DSN'),
        environment=env('SENTRY_ENVIRONMENT'),
        integrations=[DjangoIntegration()]
    )

SOCIAL_AUTH_TUNNISTAMO_SECRET = os.environ.get("SOCIAL_AUTH_TUNNISTAMO_SECRET")
SOCIAL_AUTH_TUNNISTAMO_KEY = os.environ.get("SOCIAL_AUTH_TUNNISTAMO_KEY")
SOCIAL_AUTH_TUNNISTAMO_OIDC_ENDPOINT = os.environ.get("SOCIAL_AUTH_TUNNISTAMO_OIDC_ENDPOINT")

KAAVOITUS_API_BASE_URL = os.environ.get("KAAVOITUS_API_BASE_URL")
KAAVOITUS_API_AUTH_TOKEN = os.environ.get("KAAVOITUS_API_AUTH_TOKEN")

GRAPH_API_LOGIN_BASE_URL = os.environ.get("GRAPH_API_LOGIN_BASE_URL")
GRAPH_API_BASE_URL = os.environ.get("GRAPH_API_BASE_URL")
GRAPH_API_APPLICATION_ID = os.environ.get("GRAPH_API_APPLICATION_ID")
GRAPH_API_TENANT_ID = os.environ.get("GRAPH_API_TENANT_ID")
GRAPH_API_CLIENT_SECRET = os.environ.get("GRAPH_API_CLIENT_SECRET")

SOCIAL_AUTH_TUNNISTAMO_AUTH_EXTRA_ARGUMENTS = {'ui_locales': 'fi'}

env_file = project_root(".env")

FILE_UPLOAD_PERMISSIONS = None

if os.path.exists(env_file):
    env.read_env(env_file)

DEBUG = env.bool("DEBUG")
SECRET_KEY = env.str("SECRET_KEY")

if DEBUG and not SECRET_KEY:
    SECRET_KEY = "xxx"

#ALLOWED_HOSTS = env.list("ALLOWED_HOSTS")
ALLOWED_HOSTS = os.environ.get('ALLOWED_HOSTS').split(',')
JWT_AUTH = {
    'JWT_AUDIENCE': os.environ.get('JWT_AUDIENCE'),
    'JWT_SECRET_KEY': os.environ.get('JWT_SECRET_KEY'),
}
DOCUMENT_EDIT_URL_FORMAT = os.environ.get('DOCUMENT_EDIT_URL_FORMAT')

DATABASES = {"default": env.db()}

CACHES = {"default": {
    "BACKEND": "django.core.cache.backends.db.DatabaseCache",
    "LOCATION": "kaavapino_api_cache_table",
    "OPTIONS": {
        "MAX_ENTRIES": 1500,
    }
}}

vars().update(env.email_url())  # EMAIL_BACKEND etc.

STATIC_URL = env.str("STATIC_URL")
MEDIA_URL = env.str("MEDIA_URL")
STATIC_ROOT = str(env("STATIC_ROOT"))
MEDIA_ROOT = str(env("MEDIA_ROOT"))

ROOT_URLCONF = "kaavapino.urls"
WSGI_APPLICATION = "kaavapino.wsgi.application"

LANGUAGE_CODE = "fi"
LOCALE_PATHS = (
    str(project_root.path('kaavapino').path('locale')),
)
TIME_ZONE = "Europe/Helsinki"
USE_I18N = True
USE_L10N = True
USE_TZ = True

DEFAULT_AUTO_FIELD = 'django.db.models.AutoField'

INSTALLED_APPS = [
    "helusers.apps.HelusersConfig",
    "helusers.apps.HelusersAdminConfig",
    "rest_framework",
    "rest_framework.authtoken",
    "django.contrib.auth",
    "django.contrib.sites",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.gis",
    "adminsortable2",
    "kaavapino",
    "projects",
    "sitecontent",
    "social_django",
    # "allauth",
    # "allauth.account",
    # "allauth.socialaccount",
    "private_storage",
    "corsheaders",
    "actstream",
    "django_filters",
    "rest_framework_gis",
    "users",
    "django_q",
    "drf_spectacular",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                'helusers.context_processors.settings',
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ]
        },
    }
]

# Social auth
#
SITE_ID = 1
AUTH_USER_MODEL = "users.User"
# SOCIALACCOUNT_PROVIDERS = {"helsinki_oidc": {"VERIFIED_EMAIL": True}}
AUTHENTICATION_BACKENDS = [
    'helusers.tunnistamo_oidc.TunnistamoOIDCAuth',
    'django.contrib.auth.backends.ModelBackend',
]
LOGIN_REDIRECT_URL = "/admin/"
LOGOUT_REDIRECT_URL = "/admin/"
ACCOUNT_LOGOUT_ON_GET = True
# SOCIALACCOUNT_ADAPTER = "helusers.adapter.SocialAccountAdapter"
# SOCIALACCOUNT_QUERY_EMAIL = True
# SOCIALACCOUNT_EMAIL_REQUIRED = True
# SOCIALACCOUNT_AUTO_SIGNUP = True

OIDC_AUTH = {"OIDC_LEEWAY": 3600}

OIDC_API_TOKEN_AUTH = {
    "AUDIENCE": env.str("TOKEN_AUTH_ACCEPTED_AUDIENCE"),
    "API_SCOPE_PREFIX": env.str("TOKEN_AUTH_ACCEPTED_SCOPE_PREFIX"),
    "REQUIRE_API_SCOPE_FOR_AUTHENTICATION": env.bool("TOKEN_AUTH_REQUIRE_SCOPE_PREFIX"),
    "ISSUER": env.str("TOKEN_AUTH_AUTHSERVER_URL"),
}

SESSION_SERIALIZER = 'django.contrib.sessions.serializers.PickleSerializer'

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {
        'stdout': {
            'level': 'INFO',
            'class': 'logging.StreamHandler',
            'stream': sys.stdout,
        },
    },
    'loggers': {
        'root': {
            'level': 'INFO',
            'handlers': ['stdout'],
        },
        'django.server': {
            'handlers': ['stdout'],
            'level': 'INFO',
            'propagate': True,
        },
    },
}

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "helusers.oidc.ApiTokenAuthentication",
        "rest_framework.authentication.SessionAuthentication",
        "rest_framework.authentication.TokenAuthentication",
    ),
    "DEFAULT_PERMISSION_CLASSES": ("rest_framework.permissions.IsAuthenticated",),
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 100,
    'DEFAULT_SCHEMA_CLASS': 'drf_spectacular.openapi.AutoSchema',
}

local_settings = project_root("local_settings.py")
if os.path.exists(local_settings):
    with open(local_settings) as fp:
        code = compile(fp.read(), local_settings, "exec")
    exec(code, globals(), locals())


# Private storage
PRIVATE_STORAGE_ROOT = MEDIA_ROOT


NGINX_X_ACCEL = env.bool("NGINX_X_ACCEL")
if not DEBUG and NGINX_X_ACCEL:
    PRIVATE_STORAGE_SERVER = "nginx"
    PRIVATE_STORAGE_INTERNAL_URL = "/private-x-accel-redirect/"


# CORS
# TODO: Lock down CORS access when things are running in production
CORS_ORIGIN_ALLOW_ALL = True

# Django Activity Stream
USE_NATIVE_JSONFIELD = True
ACTSTREAM_SETTINGS = {"USE_JSONFIELD": True}


USE_X_FORWARDED_HOST = env.bool("USE_X_FORWARDED_HOST")
CSRF_COOKIE_DOMAIN = env.str("CSRF_COOKIE_DOMAIN")
CSRF_TRUSTED_ORIGINS = os.environ.get('CSRF_TRUSTED_ORIGINS').split(',')

Q_CLUSTER = {
    "name": "projects",
    "orm": "default",
    "retry": 3600,
    "timeout": 1800,
    "max_attempts": 1,
}

# TODO: Enable in production
# HELUSERS_PASSWORD_LOGIN_DISABLED = True

SPECTACULAR_SETTINGS = {
    # path prefix is used for tagging the discovered operations.
    # use '/api/v[0-9]' for tagging apis like '/api/v1/albums' with ['albums']
    #"SCHEMA_PATH_PREFIX": r"^/api/",
    "DEFAULT_GENERATOR_CLASS": "drf_spectacular.generators.SchemaGenerator",
    # Schema generation parameters to influence how components are constructed.
    # Some schema features might not translate well to your target.
    # Demultiplexing/modifying components might help alleviate those issues.
    #
    # Create separate components for PATCH endpoints (without required list)
    "COMPONENT_SPLIT_PATCH": True,
    # Split components into request and response parts where appropriate
    "COMPONENT_SPLIT_REQUEST": False,
    # Aid client generator targets that have trouble with read-only properties.
    "COMPONENT_NO_READ_ONLY_REQUIRED": False,
    # Configuration for serving the schema with SpectacularAPIView
    "SERVE_URLCONF": None,
    # complete public schema or a subset based on the requesting user
    "SERVE_PUBLIC": True,
    # is the
    "SERVE_INCLUDE_SCHEMA": True,
    "SERVE_PERMISSIONS": ["rest_framework.permissions.AllowAny"],
    # Dictionary of configurations to pass to the SwaggerUI({ ... })
    # https://swagger.io/docs/open-source-tools/swagger-ui/usage/configuration/
    "SWAGGER_UI_SETTINGS": {
        "deepLinking": True,
    },
    "SWAGGER_UI_DIST": "//unpkg.com/swagger-ui-dist@3.35.1",
    "SWAGGER_UI_FAVICON_HREF": "//unpkg.com/swagger-ui-dist@3.35.1/favicon-32x32.png",
    # Append OpenAPI objects to path and components in addition to the generated objects
    "APPEND_PATHS": {},
    "APPEND_COMPONENTS": {},
    # DISCOURAGED - please don't use this anymore as it has tricky implications that
    # are hard to get right. For authentication, OpenApiAuthenticationExtension are
    # strongly preferred because they are more robust and easy to write.
    # However if used, the list of methods is appended to every endpoint in the schema!
    "SECURITY": [],
    # Postprocessing functions that run at the end of schema generation.
    # must satisfy interface result = hook(generator, request, public, result)
    "POSTPROCESSING_HOOKS": ["drf_spectacular.hooks.postprocess_schema_enums"],
    # Preprocessing functions that run before schema generation.
    # must satisfy interface result = hook(endpoints=result) where result
    # is a list of Tuples (path, path_regex, method, callback).
    # Example: 'drf_spectacular.hooks.preprocess_exclude_path_format'
    "PREPROCESSING_HOOKS": [],
    # enum name overrides. dict with keys "YourEnum" and their choice values "field.choices"
    "ENUM_NAME_OVERRIDES": {},
    # Adds "blank" and "null" enum choices where appropriate. disable on client generation issues
    "ENUM_ADD_EXPLICIT_BLANK_NULL_CHOICE": True,
    # function that returns a list of all classes that should be excluded from doc string extraction
    "GET_LIB_DOC_EXCLUDES": "drf_spectacular.plumbing.get_lib_doc_excludes",
    # Function that returns a mocked request for view processing. For CLI usage
    # original_request will be None.
    # interface: request = build_mock_request(method, path, view, original_request, **kwargs)
    "GET_MOCK_REQUEST": "drf_spectacular.plumbing.build_mock_request",
    # Camelize names like operationId and path parameter names
    "CAMELIZE_NAMES": False,
    # General schema metadata. Refer to spec for valid inputs
    # https://github.com/OAI/OpenAPI-Specification/blob/master/versions/3.0.3.md#openapi-object
    "TITLE": "Helsingin Kaupunki - Kaavapino - API",
    "DESCRIPTION": "Kaavapino API for planning data",
    "TOS": None,
    # Optional: MAY contain "name", "url", "email"
    "CONTACT": {},
    # Optional: MUST contain "name", MAY contain URL
    "LICENSE": {},
    "VERSION": "1.0.0",
    # Optional list of servers.
    # Each entry MUST contain "url", MAY contain "description", "variables"
    "SERVERS": [],
    # Tags defined in the global scope
    "TAGS": [],
    # Optional: MUST contain 'url', may contain "description"
    "EXTERNAL_DOCS": {},
    # Oauth2 related settings. used for example by django-oauth2-toolkit.
    # https://github.com/OAI/OpenAPI-Specification/blob/master/versions/3.0.3.md#oauth-flows-object
    "OAUTH2_FLOWS": [],
    "OAUTH2_AUTHORIZATION_URL": None,
    "OAUTH2_TOKEN_URL": None,
    "OAUTH2_REFRESH_URL": None,
    "OAUTH2_SCOPES": None,
}
