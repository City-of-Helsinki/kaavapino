from rest_framework import permissions

from projects.helpers import TRUE

class DocumentPermissions(permissions.BasePermission):
    def has_permission(self, request, view):
        preview = request.query_params.get("preview") in TRUE
        project = view.get_project()
        user = request.user

        if preview and view.action == "retrieve":
            return user.has_privilege('edit')
        elif view.action == "list":
            return user.has_privilege('edit')
        else:
            return project.user == user or user.has_privilege('admin')
