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
        elif not preview and view.action == "retrieve":
            return user.has_privilege('browse')
        else:
            return project.user == user or user.has_privilege('admin')


    def has_object_permission(self, request, view, obj):
        user = request.user
        preview = request.query_params.get("preview") in TRUE
        project = view.get_project()

        if view.action == "retrieve" and obj.project_card_default_template:
            return user.has_privilege('browse')
        elif preview and view.action == "retrieve":
            return user.has_privilege('edit')
        elif view.action == "list":
            return user.has_privilege('edit')
        else:
            return project.user == user or user.has_privilege('admin')
