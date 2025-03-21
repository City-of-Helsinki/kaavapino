from adminsortable2.admin import SortableAdminMixin, SortableInlineAdminMixin
from django import forms
from django.apps import apps
from django.contrib import admin, messages
from django.contrib.gis.admin import OSMGeoAdmin
from django.db import transaction
from django.utils import timezone
from django.utils.translation import ugettext_lazy as _
from django.core.cache import cache

from projects.models import (
    ProjectComment,
    Report,
    ReportColumn,
    ReportColumnPostfix,
    ReportFilter,
    ReportFilterAttributeChoice,
    Deadline,
    AutomaticDate,
    ForcedDate,
    DateType,
    DateCalculation,
    DeadlineDateCalculation,
    DocumentLinkFieldSet,
    DocumentLinkSection,
    ProjectDocumentDownloadLog
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
    AttributeLock,
    AttributeValueChoice,
    AttributeAutoValue,
    AttributeAutoValueMapping,
    CommonProjectPhase,
    DataRetentionPlan,
    DocumentTemplate,
    Project,
    ProjectPriority,
    ProjectAttributeFile,
    ProjectCardSection,
    ProjectCardSectionAttribute,
    ProjectFloorAreaSection,
    ProjectFloorAreaSectionAttribute,
    ProjectPhase,
    ProjectPhaseSection,
    ProjectPhaseSectionAttribute,
    ProjectPhaseDeadlineSection,
    ProjectPhaseDeadlineSectionAttribute,
    ProjectType,
    OverviewFilter,
    OverviewFilterAttribute,
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


class AttributeAutoValueMappingInline(admin.TabularInline):
    model = AttributeAutoValueMapping
    fields = ("key_str", "value_str")
    extra = 0


@admin.register(AttributeAutoValue)
class AttributeAutoValueAdmin(admin.ModelAdmin):
    inlines = (AttributeAutoValueMappingInline,)


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


@admin.register(ForcedDate)
class ForcedDateInline(admin.ModelAdmin):
    pass


@admin.register(DateType)
class DateTypeAdmin(admin.ModelAdmin):
    fields = (
        "identifier",
        "name",
        "base_datetype",
        "business_days_only",
        "dates",
        "automatic_dates",
        "exclude_selected",
    )

    def get_fields(self, request, obj=None):
        fields = list(super().get_fields(request, obj))
        if obj and obj.identifier == "lautakunnan_kokouspäivät":
            fields.append("forced_dates")
        return fields

    def save_model(self, request, obj, form, change):
        if 'forced_dates' in form.changed_data:  # Delete cached lautakunnan_kokouspäivät dates
            cache_keys = cache.keys("*")
            keys_to_delete = list(filter(lambda k: k.startswith(f"datetype_{obj.identifier}_dates_"), cache_keys))
            cache.delete_many(keys_to_delete)


class ProjectPhaseDeadlineSectionAttributeInline(SortableInlineAdminMixin, admin.TabularInline):
    model = ProjectPhaseDeadlineSectionAttribute
    extra = 0


@admin.register(ProjectPhaseDeadlineSection)
class ProjectPhaseDeadlineSectionAdmin(admin.ModelAdmin):
    inlines = (ProjectPhaseDeadlineSectionAttributeInline,)


class ProjectDeadlineInline(admin.TabularInline):
    model = ProjectDeadline
    fields = ("deadline", "date")
    readonly_fields = ("deadline",)
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
    search_fields = (
        "name",
        "identifier",
    )
    inlines = (AttributeValueChoiceInline,)
    prepopulated_fields = {"identifier": ("name",)}

    def save_model(self, request, obj, form, change):
        try:
            super().save_model(request, obj, form, change)
        except NotImplementedError as e:
            messages.set_level(request, messages.ERROR)
            messages.error(request, e)


@admin.register(AttributeLock)
class AttributeLockAdmin(admin.ModelAdmin):
    list_display = [
        "project",
        "attribute",
        "fieldset_attribute",
        "fieldset_attribute_index",
        "user",
        "timestamp",
    ]


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
        "create_principles",
        "create_draft",
    )
    fields = (
        *readonly_fields,
        "phase",
        "priority",
        "public",
        "archived",
        "onhold",
        "owner_edit_override",
        "attribute_data",
    )
    inlines = (ProjectPhaseLogInline, ProjectDeadlineInline)

    def get_form(self, request, obj=None, change=False, **kwargs):
        form = super(ProjectAdmin, self).get_form(request, obj, change, **kwargs)
        disable_widget_options(form, ['phase', 'priority'])
        return form

    def formfield_for_foreignkey(self, db_field, request=None, **kwargs):
        if db_field.name == 'phase':
            project = Project.objects.get(id=request.resolver_match.kwargs.get('object_id'))
            kwargs['queryset'] = ProjectPhase.objects.filter(
                project_subtype=project.subtype
            )
        return super(ProjectAdmin, self).formfield_for_foreignkey(db_field, request, **kwargs)

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

    def save_model(self, request, obj, form, change):
        if 'archived' in form.changed_data:
            obj.archived_at = timezone.now() if form.cleaned_data.get('archived') is True else None
        super(ProjectAdmin, self).save_model(request, obj, form, change)
        if 'phase' in form.changed_data:
            ProjectDocumentDownloadLog.objects.filter(project=obj).update(invalidated=True)

    def save_formset(self, request, obj, formset, change):
        super(ProjectAdmin, self).save_formset(request, obj, formset, change)
        instances = formset.save(commit=False)
        for instance in instances:
            if isinstance(instance, ProjectDeadline) and instance.deadline.attribute:
                project = instance.project
                project.attribute_data[instance.deadline.attribute.identifier] = instance.date
                project.save()

class ProjectCardSectionAttributeInline(SortableInlineAdminMixin, admin.TabularInline):
    model = ProjectCardSectionAttribute
    extra = 0


@admin.register(ProjectCardSection)
class ProjectCardSectionAdmin(SortableAdminMixin, admin.ModelAdmin):
    list_display = ("name",)
    inlines = (ProjectCardSectionAttributeInline,)


class DocumentLinkFieldSetInline(admin.TabularInline):
    model = DocumentLinkFieldSet
    extra = 0


@admin.register(DocumentLinkSection)
class DocumentLinkSectionAdmin(SortableAdminMixin, admin.ModelAdmin):
    list_display = ("name",)
    inlines = (DocumentLinkFieldSetInline,)


class OverviewFilterAttributeInline(admin.TabularInline):
    model = OverviewFilterAttribute
    extra = 0


@admin.register(OverviewFilter)
class OverviewFilterAdmin(admin.ModelAdmin):
    list_display = ("name",)
    inlines = (OverviewFilterAttributeInline,)


@admin.register(CommonProjectPhase)
class CommonProjectPhaseAdmin(admin.ModelAdmin):
    list_display = ("name",)
    ordering = ("index",)


class ProjectPhaseSectionInline(SortableInlineAdminMixin, admin.TabularInline):
    model = ProjectPhaseSection
    extra = 0


@admin.register(ProjectPhase)
class ProjectPhaseAdmin(admin.ModelAdmin):
    list_display = ("common_project_phase", "project_type", "project_subtype")
    exclude = ("index",)
    inlines = (ProjectPhaseSectionInline,)
    ordering = ("project_subtype__id", "index")


@admin.register(ProjectPriority)
class ProjectPriorityAdmin(admin.ModelAdmin):
    list_display = ("name", "priority")


class ProjectPhaseSectionAttributeInline(SortableInlineAdminMixin, admin.TabularInline):
    model = ProjectPhaseSectionAttribute
    extra = 0
    readonly_fields = ("relies_on",)
    can_delete = True


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


class CommonPhaseChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        return obj.name


class ReportColumnInline(SortableInlineAdminMixin, admin.TabularInline):
    model = ReportColumn
    extra = 0
    show_change_link = True
    exclude = ("condition",)
    readonly_fields = ("preview", "preview_only", "preview_title_column")



class ReportColumnPostfixInline(admin.TabularInline):
    model = ReportColumnPostfix
    extra = 0


@admin.register(ReportColumn)
class ReportColumnAdmin(admin.ModelAdmin):
    list_display = ("__str__",)
    inlines = (ReportColumnPostfixInline,)
    filter_horizontal = ("condition", "attributes")
    readonly_fields = ("preview", "preview_only", "preview_title_column")


@admin.register(Report)
class ReportAdmin(admin.ModelAdmin):
    list_display = ("name",)
    inlines = (ReportColumnInline,)
    readonly_fields = ("previewable",)


class ReportFilterAttributeChoiceInline(admin.TabularInline):
    model = ReportFilterAttributeChoice
    extra = 0


@admin.register(ReportFilter)
class ReportFilterAdmin(admin.ModelAdmin):
    list_display = ("name", "type")
    inlines = (ReportFilterAttributeChoiceInline,)
    filter_horizontal = ("attributes",)


@admin.register(DocumentTemplate)
class DocumentTemplateAdmin(admin.ModelAdmin):
    list_display = ("name", "file", "project_card_default_template")
    readonly_fields = ("project_card_default_template", "slug")

    actions = ('set_project_card_default_template',)

    def set_project_card_default_template(self, request, queryset):
        try:
            template = queryset.get()
        except (DocumentTemplate.DoesNotExist, DocumentTemplate.MultipleObjectsReturned):
            self.message_user(_('choose one template'))
            return

        DocumentTemplate.objects \
            .exclude(id=template.id) \
            .update(project_card_default_template=False)

        template.project_card_default_template = True
        template.save()

    set_project_card_default_template.short_description = _('set_project_card_default_template')

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "common_project_phase":
            return CommonPhaseChoiceField(
                queryset=CommonProjectPhase.objects.all().order_by(
                    "index",
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

#@admin.register(PhaseAttributeMatrixStructure)
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


def get_app_list(self, request):
    # Overridden get_app_list for injecting the admin descriptions
    app_dict = self._build_app_dict(request)
    app_list = sorted(app_dict.values(), key=lambda x: x['name'].lower())

    # Sort the models customably within each app.
    for app in app_list:
        for model in app["models"]:
            try:
                model_obj = apps.get_model(app["app_label"], model["object_name"])
            except Exception as e:
                continue

            model["admin_description"] = getattr(model_obj, "admin_description", None)

    return app_list

admin.AdminSite.get_app_list = get_app_list


def disable_widget_options(form, fields):
    for field in fields:
        form.base_fields[field].widget.can_add_related = False
        form.base_fields[field].widget.can_delete_related = False
        form.base_fields[field].widget.can_change_related = False


# Unregister unnecessary models
from rest_framework.authtoken.models import TokenProxy
admin.site.unregister(TokenProxy)

from actstream.models import Action, Follow
admin.site.unregister(Action)
admin.site.unregister(Follow)

from social_django.models import Association, Nonce, UserSocialAuth
admin.site.unregister(Association)
admin.site.unregister(Nonce)
admin.site.unregister(UserSocialAuth)
