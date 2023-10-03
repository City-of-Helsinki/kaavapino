from rest_framework import permissions

from projects.models.attribute import AttributeLock
from projects.helpers import get_attribute_lock_data


class AttributeLockPermissions(permissions.BasePermission):
    def has_permission(self, request, view):
        try:
            attribute_lock_data = get_attribute_lock_data(request.data["attribute_identifier"])
            if attribute_lock_data.get("fieldset_attribute_identifier"):
                attribute_lock = AttributeLock.objects.get(
                    project__name=request.data["project_name"],
                    fieldset_attribute__identifier=attribute_lock_data.get("fieldset_attribute_identifier"),
                    fieldset_attribute_index=attribute_lock_data.get("fieldset_attribute_index")
                )
            else:
                attribute_lock = AttributeLock.objects.get(
                    project__name=request.data["project_name"],
                    attribute__identifier=attribute_lock_data.get("attribute_identifier")
                )
            return attribute_lock.user == request.user or request.user.has_privilege('admin')
        except AttributeLock.DoesNotExist:
            return True
