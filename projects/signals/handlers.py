import os

from django.core.cache import cache
from django.db.models.signals import (
    pre_delete,
    pre_save,
    post_save,
    post_delete,
    m2m_changed,
)
from django.dispatch import receiver
from django_q.tasks import async_task
from django_q.models import OrmQ
from datetime import datetime

from projects.helpers import get_fieldset_path
from projects.models import (
    ProjectAttributeFile,
    Attribute,
    DataRetentionPlan,
    AttributeValueChoice,
    FieldSetAttribute,
    ProjectType,
    ProjectSubtype,
    ProjectFloorAreaSection,
    ProjectFloorAreaSectionAttribute,
    ProjectFloorAreaSectionAttributeMatrixStructure,
    ProjectFloorAreaSectionAttributeMatrixCell,
    ProjectPhase,
    ProjectPhaseSection,
    ProjectPhaseSectionAttribute,
    ProjectPhaseFieldSetAttributeIndex,
    PhaseAttributeMatrixStructure,
    PhaseAttributeMatrixCell,
    ProjectPhaseDeadlineSection,
    ProjectPhaseDeadlineSectionAttribute,
    Deadline,
    Project,
    DateType,
)
from projects.tasks import refresh_project_schedule_cache \
    as refresh_project_schedule_cache_task


@receiver([post_save, post_delete, m2m_changed], sender=Attribute)
@receiver([post_save, post_delete, m2m_changed], sender=DataRetentionPlan)
@receiver([post_save, post_delete, m2m_changed], sender=AttributeValueChoice)
@receiver([post_save, post_delete, m2m_changed], sender=FieldSetAttribute)
@receiver([post_save, post_delete, m2m_changed], sender=ProjectType)
@receiver([post_save, post_delete, m2m_changed], sender=ProjectSubtype)
@receiver([post_save, post_delete, m2m_changed], sender=ProjectFloorAreaSection)
@receiver([post_save, post_delete, m2m_changed], sender=ProjectFloorAreaSectionAttribute)
@receiver([post_save, post_delete, m2m_changed], sender=ProjectFloorAreaSectionAttributeMatrixStructure)
@receiver([post_save, post_delete, m2m_changed], sender=ProjectFloorAreaSectionAttributeMatrixCell)
@receiver([post_save, post_delete, m2m_changed], sender=ProjectPhase)
@receiver([post_save, post_delete, m2m_changed], sender=ProjectPhaseSection)
@receiver([post_save, post_delete, m2m_changed], sender=ProjectPhaseSectionAttribute)
@receiver([post_save, post_delete, m2m_changed], sender=ProjectPhaseFieldSetAttributeIndex)
@receiver([post_save, post_delete, m2m_changed], sender=PhaseAttributeMatrixStructure)
@receiver([post_save, post_delete, m2m_changed], sender=PhaseAttributeMatrixCell)
@receiver([post_save, post_delete, m2m_changed], sender=ProjectPhaseDeadlineSection)
@receiver([post_save, post_delete, m2m_changed], sender=ProjectPhaseDeadlineSectionAttribute)
@receiver([post_save, post_delete, m2m_changed], sender=Deadline)
def delete_cached_sections(*args, **kwargs):
    cache.delete("serialized_phase_sections")
    cache.delete("serialized_deadline_sections")

@receiver([post_save, m2m_changed], sender=Attribute)
def cache_fieldset_path_for_attribute(sender, instance, *args, **kwargs):
    get_fieldset_path(instance, cached=False)

@receiver([pre_save], sender=Project)
def save_attribute_data_subtype(sender, instance, *args, **kwargs):
    # TODO: hard-coded attribute identifiers are not ideal
    instance.attribute_data["kaavaprosessin_kokoluokka"] = \
        instance.phase.project_subtype.name
    instance.attribute_data["kaavaprosessin_kokoluokka_readonly"] = \
        instance.phase.project_subtype.name

    instance.attribute_data["kaavan_vaihe"] = \
        instance.phase.prefixed_name

    for attr in Attribute.objects.filter(static_property__isnull=False):
        value = getattr(instance, attr.static_property)

        # make this a model field if more options are needed
        if attr.value_type == Attribute.TYPE_USER:
            value = value.uuid

        instance.attribute_data[attr.identifier] = value

@receiver([post_save], sender=Project)
def add_to_report_cache_queue(sender, instance, *args, **kwargs):
    cache_key = 'projects.tasks.cache_selected_report_data.queue'
    queue = cache.get(cache_key, [])
    cache.set(cache_key, list(set(queue + [instance.id])), None)

@receiver([post_save, post_delete, m2m_changed], sender=Deadline)
def refresh_project_schedule_cache(sender, instance, *args, **kwargs):
    for task in OrmQ.objects.all():
        if task.name() == "refresh_project_schedule_cache":
            task.delete()

    async_task(
        refresh_project_schedule_cache_task,
        task_name="refresh_project_schedule_cache",
    )

@receiver([post_save], sender=DateType)
def delete_cached_date_types(sender, instance, *args, **kwargs):
    identifier = instance.identifier
    current_year = datetime.now().year
    for year in range(current_year - 1, current_year + 20):
        cache_key = f"datetype_{identifier}_dates_{year}"
        cache.delete(cache_key)
    cache.delete("serialized_date_types")