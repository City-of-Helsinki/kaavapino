from django.contrib import admin

from .models import Attribute, AttributeValueChoice, DocumentTemplate, Project, ProjectPhase, ProjectType


class AttributeValueChoiceInline(admin.TabularInline):
    model = AttributeValueChoice
    extra = 0
    prepopulated_fields = {'slug': ('value',)}


@admin.register(Attribute)
class AttributeAdmin(admin.ModelAdmin):
    prepopulated_fields = {'slug': ('name',)}
    inlines = (AttributeValueChoiceInline,)


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ('name', 'created_at', 'modified_at')


@admin.register(ProjectPhase)
class ProjectPhaseAdmin(admin.ModelAdmin):
    list_display = ('name', 'project_type')


@admin.register(ProjectType)
class ProjectTypeAdmin(admin.ModelAdmin):
    list_display = ('name',)


@admin.register(DocumentTemplate)
class DocumentTemplateAdmin(admin.ModelAdmin):
    list_display = ('name', 'file')
