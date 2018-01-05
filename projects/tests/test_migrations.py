# this can be removed as soon as we have actual tests

import pytest


@pytest.mark.django_db
def test_migrations():
    assert True
