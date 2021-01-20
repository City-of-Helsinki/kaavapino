from django.apps import AppConfig as DjangoAppConfig


class AppConfig(DjangoAppConfig):
    name = "projects"

    def ready(self):
        import projects.signals.handlers  # noqa
        from actstream import registry

        registry.register(self.get_model("Project"))
        registry.register(self.get_model("Attribute"))
        registry.register(self.get_model("Deadline"))
