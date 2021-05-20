from adminsortable2.admin import SortableAdminMixin, SortableInlineAdminMixin
from django.contrib import admin
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
