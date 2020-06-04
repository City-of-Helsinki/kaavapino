from django.contrib.auth.admin import UserAdmin, GroupAdmin
from django.contrib.auth.models import Group

from helusers.admin import admin
from helusers.models import ADGroupMapping

from .models import User, GroupPrivilege


admin.site.unregister(Group)

@admin.register(User)
class UserAdmin(UserAdmin):
    pass

class GroupPrivilegeInline(admin.TabularInline):
    model = GroupPrivilege
    can_delete = False

class ADGroupMappingInline(admin.TabularInline):
    model = ADGroupMapping
    extra = 0

@admin.register(Group)
class GroupAdmin(GroupAdmin):
    exclude = ('permissions',)
    inlines = [
        ADGroupMappingInline,
        GroupPrivilegeInline,
    ]
