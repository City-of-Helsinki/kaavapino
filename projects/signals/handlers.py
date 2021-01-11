import os

from django.core.cache import cache
from django.db.models.signals import (
    pre_delete, post_save, post_delete, m2m_changed
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
)


@receiver(pre_delete, sender=ProjectAttributeFile)
def delete_file_pre_delete_post(sender, instance, *args, **kwargs):
    if instance.file:
        path = instance.file.path
        if os.path.isfile(path):
            os.remove(path)

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
