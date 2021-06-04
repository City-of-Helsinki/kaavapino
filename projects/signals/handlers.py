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
)


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

@receiver([pre_save], sender=Project)
def save_attribute_data_subtype(sender, instance, *args, **kwargs):
    # TODO: hard-coded attribute identifiers are not ideal
    instance.attribute_data["kaavaprosessin_kokoluokka"] = \
        instance.phase.project_subtype.name

    instance.attribute_data["kaavan_vaihe"] = \
        instance.phase.prefixed_name

    for attr in Attribute.objects.filter(static_property__isnull=False):
        value = getattr(instance, attr.static_property)

        # make this a model field if more options are needed
        if attr.value_type == Attribute.TYPE_USER:
            value = value.uuid

        instance.attribute_data[attr.identifier] = value
