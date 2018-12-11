from django.apps import AppConfig as DjangoAppConfig


class AppConfig(DjangoAppConfig):
    name = "users"

    def ready(self):
        import users.signals.handlers  # noqa
        from actstream import registry

        registry.register(self.get_model("User"))
