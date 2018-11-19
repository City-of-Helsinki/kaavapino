from django.utils.translation import ugettext_lazy as _
from rest_framework.exceptions import ValidationError

from users.groups import GROUPS


def admin_or_read_only(value, attribute, instance, context):
    user = context["request"].user

    # No checks if phase has not changed
    if getattr(instance, attribute, None) == value:
        return value

    # Do not allow non admins to change the value
    is_admin = user.is_in_group(GROUPS.ADMINISTRATOR)
    if not is_admin:
        raise ValidationError(
            _(f"You are not permitted to change the {attribute} of this project")
        )

    return value
