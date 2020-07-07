from django.apps import AppConfig as DjangoAppConfig


class AppConfig(DjangoAppConfig):
    name = "sitecontent"
    verbose_name = _("site content")
