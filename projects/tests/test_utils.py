import pytest

from projects.models import Attribute
from projects.models.utils import truncate_identifier
from projects.serializers.utils import _is_attribute_required


@pytest.mark.django_db()
def test_is_attribute_required(f_short_string_attribute):
    required = _is_attribute_required(f_short_string_attribute)
    assert required is False

    # required = True
    f_short_string_attribute.required = True
    required = _is_attribute_required(f_short_string_attribute)
    assert required is True

    # required = True, generated = True
    f_short_string_attribute.generated = True
    required = _is_attribute_required(f_short_string_attribute)
    assert required is False

    # required = True, generated = False, Boolean field
    f_short_string_attribute.generated = False
    f_short_string_attribute.value_type = Attribute.TYPE_BOOLEAN
    required = _is_attribute_required(f_short_string_attribute)
    assert required is False


def test_identifier_truncation():
    identifier = "identifier"

    # Length is the same, nothing is done
    truncated_identifier = truncate_identifier(identifier, length=len(identifier))
    assert identifier == truncated_identifier

    # Length is bigger, not thing is done
    truncated_identifier = truncate_identifier(identifier, length=len(identifier) + 5)
    assert identifier == truncated_identifier

    # Length is smaller, identifier is truncated
    truncated_identifier = truncate_identifier(identifier, length=len(identifier) - 1)
    assert identifier != truncated_identifier
    assert identifier[:-5] == truncated_identifier[:-4]
    assert len(truncated_identifier) == len(identifier) - 1

    # Check that truncation produces the currently expected result (sha1)
    assert truncated_identifier == "identfae9"

    # Truncating consistently returns the same result
    t1 = truncate_identifier(identifier, length=len(identifier) - 1)
    t2 = truncate_identifier(identifier, length=len(identifier) - 1)

    assert t1 == t2
