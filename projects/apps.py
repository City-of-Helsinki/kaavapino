from django.apps import AppConfig as DjangoAppConfig


class AppConfig(DjangoAppConfig):
    name = "projects"

    def ready(self):
        import projects.signals.handlers  # noqa
