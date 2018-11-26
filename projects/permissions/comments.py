from rest_framework import permissions


class CommentPermissions(permissions.BasePermission):
    def has_object_permission(self, request, view, obj):
        # Read is always allowed
        if request.method in permissions.SAFE_METHODS:
            return True

        # Must be owner to modify
        return obj.user == request.user
