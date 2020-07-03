from adminsortable2.admin import SortableInlineAdminMixin
from django.contrib import admin
from sitecontent.models import FooterSection, FooterLink


class FooterLinkInline(SortableInlineAdminMixin, admin.TabularInline):
    model = FooterLink
    extra = 1

@admin.register(FooterSection)
class FooterSectionAdmin(admin.ModelAdmin):
    inlines = (FooterLinkInline,)
