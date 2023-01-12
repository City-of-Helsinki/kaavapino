from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.contrib.auth.admin import GroupAdmin as DjangoGroupAdmin
from django.contrib.auth.models import Group
from django.utils.translation import gettext_lazy as _

from helusers.admin import admin
from helusers.models import ADGroupMapping

from .helpers import has_django_admin_attributes
from .models import User, GroupPrivilege


admin.site.unregister(Group)

@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    def formfield_for_manytomany(self, db_field, request, **kwargs):
        if db_field.name == "additional_groups":
            user = User.objects.get(pk=request.resolver_match.kwargs['object_id'])
            kwargs["queryset"] = (
                user.additional_groups.all() | \
                Group.objects.exclude(user=user)
            ).distinct().order_by("name")
        return super(UserAdmin, self).formfield_for_manytomany(db_field, request, **kwargs)

    fieldsets = DjangoUserAdmin.fieldsets
    for fieldset in fieldsets:
        if "groups" in fieldset[1]["fields"]:
            fieldlist = list(fieldset[1]["fields"])
            fieldlist += ["additional_groups"]
            fieldlist.remove("user_permissions")
            fieldset[1]["fields"] = tuple(fieldlist),
            break

    filter_horizontal = DjangoUserAdmin.filter_horizontal + ("additional_groups",)
    readonly_fields = DjangoUserAdmin.readonly_fields + (
        "groups",
        "date_joined",
        "last_login",
        "first_name",
        "last_name",
        "is_staff",
        "is_superuser",
    )
    list_display = DjangoUserAdmin.list_display + ('hide_from_ui',)
    actions = ('hide_users_from_ui', 'show_users_in_ui')

    @has_django_admin_attributes
    def hide_users_from_ui(self, request, queryset):
        users = queryset.all()
        users.update(hide_from_ui=True)

    @has_django_admin_attributes
    def show_users_in_ui(self, request, queryset):
        users = queryset.all()
        users.update(hide_from_ui=False)

    hide_users_from_ui.short_description = _('hide from ui')
    show_users_in_ui.short_description = _('show in ui')

    class Meta:
        fields = '__all__'


class GroupPrivilegeInline(admin.TabularInline):
    model = GroupPrivilege
    can_delete = False

class ADGroupMappingInline(admin.TabularInline):
    model = ADGroupMapping
    extra = 0

@admin.register(Group)
class GroupAdmin(DjangoGroupAdmin):
    exclude = ('permissions',)
    inlines = [
        ADGroupMappingInline,
        GroupPrivilegeInline,
    ]
