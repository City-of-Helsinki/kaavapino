from adminsortable2.admin import SortableInlineAdminMixin
from django import forms
from django.contrib import admin, messages
from django.contrib.gis.admin import OSMGeoAdmin
from django.db import transaction
from django.utils.translation import ugettext_lazy as _

from projects.models import (
    ProjectComment,
    Report,
    ReportAttribute,
    Deadline,
    AutomaticDate,
    DateType,
    DateCalculation,
    DeadlineDateCalculation,
)
from projects.models.project import (
    ProjectPhaseLog,
    PhaseAttributeMatrixStructure,
    PhaseAttributeMatrixCell,
    ProjectFloorAreaSectionAttributeMatrixStructure,
    ProjectFloorAreaSectionAttributeMatrixCell,
    ProjectSubtype,
    ProjectDeadline,
)
from .exporting import get_document_response
from .models import (
    Attribute,
    AttributeValueChoice,
    DataRetentionPlan,
    DocumentTemplate,
    Project,
    ProjectAttributeFile,
    ProjectFloorAreaSection,
    ProjectFloorAreaSectionAttribute,
    ProjectPhase,
    ProjectPhaseSection,
    ProjectPhaseSectionAttribute,
    ProjectPhaseDeadlineSection,
    ProjectPhaseDeadlineSectionAttribute,
    ProjectType,
)

class InitialCalculationInline(SortableInlineAdminMixin, admin.TabularInline):
    model = DeadlineDateCalculation
    extra = 0
    ordering = ("index",)
    verbose_name = _("initial calculation")
    verbose_name_plural = _("initial calculations")

    def get_queryset(self, request):
        deadline_id = request.resolver_match.kwargs['object_id']
        return Deadline.objects.get(id=deadline_id).initial_calculations


class UpdateCalculationInline(SortableInlineAdminMixin, admin.TabularInline):
    model = DeadlineDateCalculation
    extra = 0
    ordering = ("index",)
    verbose_name = _("update calculation")
    verbose_name_plural = _("update calculations")

    def get_queryset(self, request):
        deadline_id = request.resolver_match.kwargs['object_id']
        return Deadline.objects.get(id=deadline_id).update_calculations


@admin.register(DateCalculation)
class DateCalculation(admin.ModelAdmin):
    def get_model_perms(self, request):
        return {}


@admin.register(Deadline)
class DeadlineAdmin(admin.ModelAdmin):
    inlines = (InitialCalculationInline, UpdateCalculationInline)
    exclude = ("initial_calculations", "update_calculations")


@admin.register(AutomaticDate)
class AutomaticDateInline(admin.ModelAdmin):
    fields = (
        "name",
        "weekdays",
        "week",
        "start_date",
        "end_date",
        "before_holiday",
        "after_holiday",
    )

    def get_model_perms(self, request):
        return {}


@admin.register(DateType)
class DateTypeAdmin(admin.ModelAdmin):
    pass


class ProjectPhaseDeadlineSectionAttributeInline(SortableInlineAdminMixin, admin.TabularInline):
    model = ProjectPhaseDeadlineSectionAttribute
    extra = 0


@admin.register(ProjectPhaseDeadlineSection)
class ProjectPhaseDeadlineSectionAdmin(admin.ModelAdmin):
    inlines = (ProjectPhaseDeadlineSectionAttributeInline,)


class ProjectDeadlineInline(admin.TabularInline):
    model = ProjectDeadline
    fields = ("deadline", "date")
    readonly_fields = ("deadline", "date")
    extra = 0
    can_delete = False


class AttributeValueChoiceInline(SortableInlineAdminMixin, admin.TabularInline):
    model = AttributeValueChoice
    extra = 0
    prepopulated_fields = {"identifier": ("value",)}


@admin.register(Attribute)
class AttributeAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "value_type",
        "identifier",
        "required",
        "public",
        "data_retention_plan",
        "highlight_group",
    )
    inlines = (AttributeValueChoiceInline,)
    prepopulated_fields = {"identifier": ("name",)}

    def save_model(self, request, obj, form, change):
        try:
            super().save_model(request, obj, form, change)
        except NotImplementedError as e:
            messages.set_level(request, messages.ERROR)
            messages.error(request, e)


def build_create_document_action(template):
    def create_document(modeladmin, request, queryset):
        if queryset.count() > 1:
            messages.error(request, _("Please select only one project."))
            return None
        project = queryset.first()
        return get_document_response(project, template)

    create_document.short_description = _("Create document {}").format(template.name)
    create_document.__name__ = "create_document_{}".format(template.id)

    return create_document


class ProjectPhaseLogInline(admin.TabularInline):
    model = ProjectPhaseLog
    fields = ("phase", "user", "created_at")
    readonly_fields = ("project", "phase", "user", "created_at")
    can_delete = False
    extra = 0
    max_num = 0


@admin.register(Project)
class ProjectAdmin(OSMGeoAdmin):
    list_display = ("name", "created_at", "modified_at")
    readonly_fields = (
        "name",
        "user",
        "created_at",
        "modified_at",
        "pino_number",
        "subtype",
        "phase",
        "create_principles",
        "create_draft",
    )
    fields = (
        *readonly_fields,
        "public",
        "archived",
        "onhold",
        "owner_edit_override",
    )
    inlines = (ProjectPhaseLogInline, ProjectDeadlineInline)

    def get_actions(self, request):
        actions = super().get_actions(request)

        for template in DocumentTemplate.objects.all():
            action = build_create_document_action(template)
            actions[action.__name__] = (
                action,
                action.__name__,
                action.short_description,
            )

        return actions


class ProjectPhaseSectionInline(SortableInlineAdminMixin, admin.TabularInline):
    model = ProjectPhaseSection
    extra = 0


@admin.register(ProjectPhase)
class ProjectPhaseAdmin(admin.ModelAdmin):
    list_display = ("name", "project_type", "project_subtype")
    exclude = ("index",)
    inlines = (ProjectPhaseSectionInline,)
    ordering = ("project_subtype__id", "index")


class ProjectPhaseSectionAttributeInline(SortableInlineAdminMixin, admin.TabularInline):
    model = ProjectPhaseSectionAttribute
    extra = 0


@admin.register(ProjectPhaseSection)
class ProjectPhaseSectionAdmin(admin.ModelAdmin):
    list_display = ("name", "phase")
    exclude = ("index",)
    inlines = (ProjectPhaseSectionAttributeInline,)
    ordering = ("phase__project_subtype__id", "phase__index", "index")


class ProjectPhaseInline(SortableInlineAdminMixin, admin.TabularInline):
    model = ProjectPhase
    extra = 0


class ProjectProjectSubtypeInline(SortableInlineAdminMixin, admin.TabularInline):
    model = ProjectSubtype
    extra = 0


@admin.register(ProjectSubtype)
class ProjectSubtypeAdmin(admin.ModelAdmin):
    list_display = ("name",)
    inlines = (ProjectPhaseInline,)


@admin.register(ProjectType)
class ProjectTypeAdmin(admin.ModelAdmin):
    list_display = ("name",)
    inlines = (ProjectProjectSubtypeInline,)


class PhaseChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        return f"{obj.project_subtype.name}: {obj.name}"


@admin.register(DocumentTemplate)
class DocumentTemplateAdmin(admin.ModelAdmin):
    list_display = ("name", "file")
    readonly_fields = ("slug",)

    # Hide this from admin for now
    def get_model_perms(self, request):
        return {}

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "project_phase":
            return PhaseChoiceField(
                queryset=ProjectPhase.objects.all().order_by(
                    "project_subtype__index", "index"
                )
            )
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


class PhaseSectionChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        return f"{obj.phase.project_subtype.name}: {obj.name}"


class ProjectFloorAreaSectionChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        return f"{obj.project_subtype.name}: {obj.name}"


# class BaseMatrixStructureAdmin(admin.Model):

@admin.register(PhaseAttributeMatrixStructure)
class PhaseAttributeMatrixStructureAdmin(admin.ModelAdmin):
# class PhaseAttributeMatrixStructureAdmin(BaseMatrixStructureAdmin):
    change_form_template = "admin/matrix.html"

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "section":
            return PhaseSectionChoiceField(
                queryset=ProjectPhaseSection.objects.all().order_by(
                    "phase__project_subtype__index", "index"
                )
            )
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def render_change_form(
        self, request, context, add=False, change=False, form_url="", obj=None
    ):
        cell_rows = []
        if obj:
            x_range = range(len(obj.column_names))
            y_range = range(len(obj.row_names))

            # Fill matrix with None values
            cell_rows = [[None for x in x_range] for y in y_range]

            # Fill in the phase attributes that exists
            for cell in obj.phaseattributematrixcell_set.all():
                cell_rows[cell.row][cell.column] = cell

            # Create select dropdown choices
            attribute_choices = {None: "-"}
            section_attributes = ProjectPhaseSectionAttribute.objects.filter(
                section=obj.section
            )
            for section_attribute in section_attributes:
                attribute_choices[
                    section_attribute.pk
                ] = section_attribute.attribute.name
            context["attribute_choices"] = attribute_choices

        context["cells"] = cell_rows
        return super().render_change_form(request, context, add, change, form_url, obj)

    def save_model(self, request, obj, form, change):
        post_data = request.POST
        attribute_values = {
            field: data
            for field, data in post_data.items()
            if "attribute_matrix" in field and data not in ["None", None]
        }

        with transaction.atomic():
            # Save the structure object
            super().save_model(request, obj, form, change)
            structure = PhaseAttributeMatrixStructure.objects.get(pk=obj.pk)

            row_limit = (
                len(structure.row_names) - 1 if len(structure.row_names) > 0 else 0
            )
            column_limit = (
                len(structure.column_names) - 1
                if len(structure.column_names) > 0
                else 0
            )

            # Remove all existing matrix cells
            PhaseAttributeMatrixCell.objects.filter(structure=structure).delete()

            # Add the cell data to the structure
            for field, data in attribute_values.items():
                section_attribute = ProjectPhaseSectionAttribute.objects.filter(
                    pk=int(data)
                ).first()
                if not section_attribute:
                    continue
                row, column = field.split("-")[1:]
                row = int(row)
                column = int(column)

                if row > row_limit or column > column_limit:
                    continue

                PhaseAttributeMatrixCell.objects.create(
                    attribute=section_attribute,
                    row=row,
                    column=column,
                    structure=structure,
                )


@admin.register(ProjectFloorAreaSectionAttributeMatrixStructure)
class ProjectFloorAreaSectionAttributeMatrixStructureAdmin(admin.ModelAdmin):
    change_form_template = "admin/matrix.html"

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "section":
            return ProjectFloorAreaSectionChoiceField(
                queryset=ProjectFloorAreaSection.objects.all().order_by(
                    "project_subtype__index", "index"
                )
            )
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def render_change_form(
        self, request, context, add=False, change=False, form_url="", obj=None
    ):
        cell_rows = []
        if obj:
            x_range = range(len(obj.column_names))
            y_range = range(len(obj.row_names))

            # Fill matrix with None values
            cell_rows = [[None for x in x_range] for y in y_range]

            # Fill in the phase attributes that exists
            for cell in obj.projectfloorareasectionattributematrixcell_set.all():
                cell_rows[cell.row][cell.column] = cell

            # Create select dropdown choices
            attribute_choices = {None: "-"}
            section_attributes = ProjectFloorAreaSectionAttribute.objects.filter(
                section=obj.section
            )
            for section_attribute in section_attributes:
                attribute_choices[
                    section_attribute.pk
                ] = section_attribute.attribute.name
            context["attribute_choices"] = attribute_choices

        context["cells"] = cell_rows
        return super().render_change_form(request, context, add, change, form_url, obj)

    def save_model(self, request, obj, form, change):
        post_data = request.POST
        attribute_values = {
            field: data
            for field, data in post_data.items()
            if "attribute_matrix" in field and data not in ["None", None]
        }

        with transaction.atomic():
            # Save the structure object
            super().save_model(request, obj, form, change)
            structure = ProjectFloorAreaSectionAttributeMatrixStructure.objects.get(pk=obj.pk)

            row_limit = (
                len(structure.row_names) - 1 if len(structure.row_names) > 0 else 0
            )
            column_limit = (
                len(structure.column_names) - 1
                if len(structure.column_names) > 0
                else 0
            )

            # Remove all existing matrix cells
            ProjectFloorAreaSectionAttributeMatrixCell.objects.filter(structure=structure).delete()

            # Add the cell data to the structure
            for field, data in attribute_values.items():
                section_attribute = ProjectFloorAreaSectionAttribute.objects.filter(
                    pk=int(data)
                ).first()
                if not section_attribute:
                    continue
                row, column = field.split("-")[1:]
                row = int(row)
                column = int(column)

                if row > row_limit or column > column_limit:
                    continue

                ProjectFloorAreaSectionAttributeMatrixCell.objects.create(
                    attribute=section_attribute,
                    row=row,
                    column=column,
                    structure=structure,
                )


class ProjectFloorAreaSectionAttributeInline(
    admin.TabularInline
):
    model = ProjectFloorAreaSectionAttribute
    extra = 0


@admin.register(ProjectFloorAreaSection)
class ProjectFloorAreaSectionAdmin(admin.ModelAdmin):
    inlines = (ProjectFloorAreaSectionAttributeInline,)


@admin.register(ProjectComment)
class ProjectComment(admin.ModelAdmin):
    def get_model_perms(self, request):
        return {}


@admin.register(DataRetentionPlan)
class DataRetentionPlanAdmin(admin.ModelAdmin):
    def get_model_perms(self, request):
        return {}


admin.site.index_template = "admin/kaavapino_index.html"
