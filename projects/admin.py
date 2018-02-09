from adminsortable2.admin import SortableInlineAdminMixin
from django.contrib import admin, messages
from django.contrib.gis.admin import OSMGeoAdmin
from django.utils.translation import ugettext_lazy as _

from .exporting import get_document_response
from .models import (
    Attribute, AttributeValueChoice, DocumentTemplate, Project, ProjectAttributeImage, ProjectPhase,
    ProjectPhaseSection, ProjectPhaseSectionAttribute, ProjectType
)


class AttributeValueChoiceInline(SortableInlineAdminMixin, admin.TabularInline):
    model = AttributeValueChoice
    extra = 0
    prepopulated_fields = {'identifier': ('value',)}


@admin.register(Attribute)
class AttributeAdmin(admin.ModelAdmin):
    list_display = ('name', 'value_type', 'identifier')
    inlines = (AttributeValueChoiceInline,)
    prepopulated_fields = {'identifier': ('name',)}

    def save_model(self, request, obj, form, change):
        try:
            super().save_model(request, obj, form, change)
        except NotImplementedError as e:
            messages.set_level(request, messages.ERROR)
            messages.error(request, e)


def build_create_document_action(template):
    def create_document(modeladmin, request, queryset):
        if queryset.count() > 1:
            messages.error(request, _('Please select only one project.'))
            return None
        project = queryset.first()
        return get_document_response(project, template)

    create_document.short_description = _('Create document {}').format(template.name)
    create_document.__name__ = 'create_document_{}'.format(template.id)

    return create_document


@admin.register(Project)
class ProjectAdmin(OSMGeoAdmin):
    list_display = ('name', 'created_at', 'modified_at')

    def get_actions(self, request):
        actions = super().get_actions(request)

        for template in DocumentTemplate.objects.all():
            action = build_create_document_action(template)
            actions[action.__name__] = (action, action.__name__, action.short_description)

        return actions


class ProjectPhaseSectionInline(SortableInlineAdminMixin, admin.TabularInline):
    model = ProjectPhaseSection
    extra = 0


@admin.register(ProjectPhase)
class ProjectPhaseAdmin(admin.ModelAdmin):
    list_display = ('name', 'project_type')
    exclude = ('index',)
    inlines = (ProjectPhaseSectionInline,)


class ProjectPhaseSectionAttributeInline(SortableInlineAdminMixin, admin.TabularInline):
    model = ProjectPhaseSectionAttribute
    extra = 0


@admin.register(ProjectPhaseSection)
class ProjectPhaseSectionAdmin(admin.ModelAdmin):
    list_display = ('name', 'phase')
    exclude = ('index',)
    inlines = (ProjectPhaseSectionAttributeInline,)
    ordering = ('phase', 'index')


class ProjectPhaseInline(SortableInlineAdminMixin, admin.TabularInline):
    model = ProjectPhase
    extra = 0


@admin.register(ProjectType)
class ProjectTypeAdmin(admin.ModelAdmin):
    list_display = ('name',)
    inlines = (ProjectPhaseInline,)


@admin.register(DocumentTemplate)
class DocumentTemplateAdmin(admin.ModelAdmin):
    list_display = ('name', 'file')


@admin.register(ProjectAttributeImage)
class ProjectAttributeImageAdmin(admin.ModelAdmin):
    pass
