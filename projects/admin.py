from django.contrib import admin, messages
from django.utils.translation import ugettext_lazy as _

from .exporting import get_document_response
from .models import Attribute, AttributeValueChoice, DocumentTemplate, Project, ProjectPhase, ProjectType


class AttributeValueChoiceInline(admin.TabularInline):
    model = AttributeValueChoice
    extra = 0


@admin.register(Attribute)
class AttributeAdmin(admin.ModelAdmin):
    inlines = (AttributeValueChoiceInline,)


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
class ProjectAdmin(admin.ModelAdmin):
    list_display = ('name', 'created_at', 'modified_at')

    def get_actions(self, request):
        actions = super().get_actions(request)

        for template in DocumentTemplate.objects.all():
            action = build_create_document_action(template)
            actions[action.__name__] = (action, action.__name__, action.short_description)

        return actions


@admin.register(ProjectPhase)
class ProjectPhaseAdmin(admin.ModelAdmin):
    list_display = ('name', 'project_type')


@admin.register(ProjectType)
class ProjectTypeAdmin(admin.ModelAdmin):
    list_display = ('name',)


@admin.register(DocumentTemplate)
class DocumentTemplateAdmin(admin.ModelAdmin):
    list_display = ('name', 'file')
