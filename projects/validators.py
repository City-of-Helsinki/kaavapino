from django.utils.translation import ugettext_lazy as _
from rest_framework.exceptions import PermissionDenied


def admin_or_read_only(value, attribute, instance, context):
    user = context["request"].user

    # No checks if value has not changed
    if getattr(instance, attribute, None) == value:
        return value

    # Do not allow non admins to change the value
    is_admin = user.has_privilege('admin')
    if not is_admin:
        raise PermissionDenied(
            _(f"You are not permitted to change the {attribute} of this project")
        )

    return value
