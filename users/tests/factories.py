import factory

from users.models import User


class UserFactory(factory.DjangoModelFactory):
    first_name = factory.Faker("first_name", locale="fi_FI")
    last_name = factory.Faker("last_name", locale="fi_FI")
    username = factory.LazyAttribute(
        lambda o: f"{o.first_name.lower()}.{o.last_name.lower()}"
    )
    email = factory.LazyAttribute(lambda o: f"{o.username}@example.com")

    class Meta:
        model = User
