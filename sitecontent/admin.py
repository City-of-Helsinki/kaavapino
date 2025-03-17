from adminsortable2.admin import SortableAdminMixin, SortableInlineAdminMixin
from django.contrib import admin, messages
from django.contrib.admin.models import LogEntry
from django.db.models import Q

from projects.importing import AttributeImporter, AttributeImporterException, DeadlineImporter, DeadlineImporterException
from sitecontent.models import ExcelFile

from sitecontent.models import (
    FooterSection,
    FooterLink,
    ListViewAttributeColumn,
    TargetFloorArea,
)

from django_q.tasks import async_task
from django.core.cache import cache
from projects.importing import attribute, deadline
from openpyxl import load_workbook

import json
import traceback

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


def get_importer(obj):
    options = {
        "filename": obj.file.path,
        "kv": "1.0",
        **json.loads(obj.options)
    }
    return AttributeImporter(options) if obj.type == ExcelFile.TYPE_ATTRIBUTES \
        else DeadlineImporter(options) if obj.type == ExcelFile.TYPE_DEADLINES \
        else None

def clear_cache():
    keys_to_clear = ["serialized_project_schedules",
                     "project_phase_section_filters",
                     "deadline_sections",
                     "projects.helpers.get_fieldset_path",
                     "projects.helpers.get_flat_attribute_data",
                     "phase_schema",
                     "deadline_update_dependencies",
                     "deadline_initial_dependencies"
                     ]
    cache_keys = cache.keys("*")
    keys_to_delete = []
    for key in keys_to_clear:
        keys_to_delete.extend(list(filter(lambda k: k.startswith(key), cache_keys)))
    cache.delete_many(keys_to_delete)

def activate_excel(obj):
    try:
        importer = get_importer(obj)
        importer.run()
        clear_cache()
        obj.update(status=ExcelFile.STATUS_ACTIVE, error=None, task_id=None)
        ExcelFile.objects.all().exclude(~Q(type=obj.type) | Q(file=obj.file)).update(status=ExcelFile.STATUS_INACTIVE, updated=None, task_id=None)
    except (AttributeImporterException,DeadlineImporterException, Exception) as e:
        obj.update(status=ExcelFile.STATUS_ERROR, error=traceback.format_exception_only(e), task_id=None)

@admin.action
def activate(modeladmin, request, queryset):
    if queryset.count() == 1:
        object = queryset.first()
        if object.status == ExcelFile.STATUS_ACTIVE or object.type == ExcelFile.TYPE_UNKNOWN:
            messages.add_message(request, messages.WARNING, "Unable to activate file -- File already active or invalid")
            return

        if ExcelFile.objects.filter(status=ExcelFile.STATUS_UPDATING).count() > 0:
            messages.add_message(request, messages.WARNING, "Unable to activate file -- Other file already updating")
            return

        task_id = async_task(
            activate_excel,
            object
        )
        object.update(status=ExcelFile.STATUS_UPDATING, error=None, task_id=task_id)
        messages.add_message(request, messages.INFO, f"Updating {object.file.path}")

@admin.register(ExcelFile)
class ExcelFileAdmin(admin.ModelAdmin):
    list_display = (
        'uploaded',
        'file',
        'type',
        'status',
        'task_id',
        'updated',
        'options',
    )
    readonly_fields = (
        'uploaded',
        'type',
        'status',
        'updated',
        'error',
        'task_id',
    )
    fields = (
        *readonly_fields,
        'file',
        'options',
    )
    actions = [activate]

    def has_change_permission(self, request, obj=None):
        return False

    def has_view_permission(self, request, obj=None):
        return request.user.has_privilege('admin')

    def get_worksheet(self, workbook, name):
        try:
            return workbook.get_sheet_by_name(name)
        except KeyError:
            return None

    def save_model(self, request, obj, form, change):
        file = obj.file

        workbook = load_workbook(file, read_only=True, data_only=True)
        if self.get_worksheet(workbook, attribute.DEFAULT_SHEET_NAME):
            obj.type = ExcelFile.TYPE_ATTRIBUTES
        elif self.get_worksheet(workbook, deadline.DEADLINES_SHEET_NAME):
            obj.type = ExcelFile.TYPE_DEADLINES
        else:
            obj.type = ExcelFile.TYPE_UNKNOWN

        super(ExcelFileAdmin, self).save_model(request, obj, form, change)