from django.db import models
from django.urls import reverse_lazy
from django.utils.translation import ugettext_lazy as _
from private_storage.fields import PrivateFileField

from projects.models.utils import KaavapinoPrivateStorage
from .project import ProjectPhase


class DocumentTemplate(models.Model):
    """Document that is produced in a certain phase of a project. Project attribute
    data is rendered into the given document template.
    """

    name = models.CharField(max_length=255, verbose_name=_("name"))
    project_phase = models.ForeignKey(
        ProjectPhase,
        verbose_name=_("project phase"),
        related_name="document_templates",
        on_delete=models.CASCADE,
    )

    def get_upload_subfolder(self):
        phase_name = slugify(self.project_phase.name)
        return ["document_templates", phase_name, self.slug]

    file = PrivateFileField(
        "File",
        storage=KaavapinoPrivateStorage(
            base_url=reverse_lazy(
                "serve_private_document_template_file", kwargs={"path": ""}
            ),
            url_postfix="document_templates",
        ),
        upload_subfolder=get_upload_subfolder,
        max_length=255,
    )

    class Meta:
        verbose_name = _("document template")
        verbose_name_plural = _("document templates")

    def __str__(self):
        return self.name
