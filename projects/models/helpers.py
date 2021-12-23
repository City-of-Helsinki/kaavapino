import re
from django.core.validators import RegexValidator
from django.utils.translation import gettext_lazy as _


DATE_SERIALIZATION_FORMAT = "%Y-%m-%d"

identifier_re = re.compile(r"^[\w]+\Z")

validate_identifier = RegexValidator(
    identifier_re,
    _(
        "Enter a valid 'identifier' consisting of Unicode letters, numbers or underscores."
    ),
    "invalid",
)
