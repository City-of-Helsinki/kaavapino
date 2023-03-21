from rest_framework import permissions

from projects.models.attribute import AttributeLock


class AttributeLockPermissions(permissions.BasePermission):
    def has_permission(self, request, view):
        try:
            attribute_lock = AttributeLock.objects.get(
                project__name=request.data["project_name"],
                attribute__identifier=request.data["attribute_identifier"]
            )
            return attribute_lock.user == request.user or request.user.has_privilege('admin')
        except AttributeLock.DoesNotExist:
            return True
