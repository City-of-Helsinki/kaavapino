from adminsortable2.admin import SortableAdminMixin, SortableInlineAdminMixin
from django.contrib import admin
from django.contrib.admin.models import LogEntry

from sitecontent.models import (
    FooterSection,
    FooterLink,
    ListViewAttributeColumn,
    TargetFloorArea,
)


class FooterLinkInline(SortableInlineAdminMixin, admin.TabularInline):
    model = FooterLink
    extra = 1


@admin.register(FooterSection)
class FooterSectionAdmin(admin.ModelAdmin):
    inlines = (FooterLinkInline,)


@admin.register(ListViewAttributeColumn)
class ListViewAttributeColumnAdmin(SortableAdminMixin, admin.ModelAdmin):
    list_display = ('attribute',)


@admin.register(TargetFloorArea)
class TargetFloorAreaAdmin(admin.ModelAdmin):
    pass


@admin.register(LogEntry)
class LogEntryAdmin(admin.ModelAdmin):
    # to have a date-based drilldown navigation in the admin page
    date_hierarchy = 'action_time'

    # to filter the resultes by users, content types and action flags
    list_filter = [
        'user',
        'content_type',
        'action_flag'
    ]

    # when searching the user will be able to search in both object_repr and change_message
    search_fields = [
        'object_repr',
        'change_message'
    ]

    list_display = [
        'action_time',
        'user',
        'content_type',
        'action_flag',
    ]

    def has_delete_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_add_permission(self, request):
        return False

    def has_view_permission(self, request, obj=None):
        return request.user.has_privilege('admin')
