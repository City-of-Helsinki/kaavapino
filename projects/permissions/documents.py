from rest_framework import permissions


class DocumentPermissions(permissions.BasePermission):
    def has_permission(self, request, view):
        project = view.get_project()
        user = request.user

        if project.user == user or user.is_administrative_personnel():
            return True

        return False
