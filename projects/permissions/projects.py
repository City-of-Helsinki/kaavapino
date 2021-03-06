from rest_framework import permissions


class ProjectPermissions(permissions.BasePermission):
    def has_object_permission(self, request, view, obj):
        is_owner = obj.user == request.user

        if not obj.public:
            return is_owner or request.user.has_privilege('admin')

        if request.method in permissions.SAFE_METHODS:
            return request.user.has_privilege('browse')
        elif request.method in ['PUT', 'PATCH']:
            return request.user.has_privilege('edit')
        elif request.method == 'POST':
            return request.user.has_privilege('create')
        else:
            return is_owner or request.user.has_privilege('admin')
