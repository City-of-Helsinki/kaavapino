from rest_framework import permissions


class DocumentPermissions(permissions.BasePermission):
    def has_permission(self, request, view):
        project = view.get_project()
        user = request.user

        if project.user == user or user.has_privilege('admin'):
            return True

        return False
