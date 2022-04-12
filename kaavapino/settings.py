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
    HELUSERS_PASSWORD_LOGIN_DISABLED=(bool, False),
    ELASTIC_APM_SERVER_URL=(str, ""),
    ELASTIC_APM_SERVICE_NAME=(str, ""),
    ELASTIC_APM_SECRET_TOKEN=(str, ""),
)

if env.str("ELASTIC_APM_SERVER_URL") and env.str("ELASTIC_APM_SECRET_TOKEN"):
    ELASTIC_APM = {
        "DEBUG": True,
        "SERVER_URL": env.str("ELASTIC_APM_SERVER_URL"),
        "SERVICE_NAME": env.str("ELASTIC_APM_SERVICE_NAME"),
        "SECRET_TOKEN": env.str("ELASTIC_APM_SECRET_TOKEN"),
    }

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

if env.str("ELASTIC_APM_SERVER_URL") and env.str("ELASTIC_APM_SECRET_TOKEN"):
    INSTALLED_APPS += ["elasticapm.contrib.django"]

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
        "rest_framework.authentication.TokenAuthentication",
        "rest_framework.authentication.SessionAuthentication",
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

HELUSERS_PASSWORD_LOGIN_DISABLED = env.bool("HELUSERS_PASSWORD_LOGIN_DISABLED")

SPECTACULAR_SETTINGS = {
    "TITLE": "Helsingin Kaupunki - Kaavapino - API",
    "DESCRIPTION": "Kaavapino API for planning data",
    "VERSION": "1.0.0",
    "AUTHENTICATION_WHITELIST": [
        "helusers.oidc.ApiTokenAuthentication",
        "rest_framework.authentication.SessionAuthentication",
    ],
    "SCHEMA_COERCE_PATH_PK_SUFFIX": True,
    # OTHER SETTINGS
    "DISABLE_ERRORS_AND_WARNINGS": True,
    "SWAGGER_UI_SETTINGS": {
        "deepLinking": True,
        "persistAuthorization": True,
    },
}
