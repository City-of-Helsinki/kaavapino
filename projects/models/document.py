from django.db import models
from django.urls import reverse_lazy
from django.utils.text import slugify
from django.utils.translation import ugettext_lazy as _
from private_storage.fields import PrivateFileField

from projects.models.utils import KaavapinoPrivateStorage
from .project import CommonProjectPhase


class DocumentTemplate(models.Model):
    """Document that is produced in a certain phase of a project. Project attribute
    data is rendered into the given document template.
    """

    name = models.CharField(max_length=255, verbose_name=_("name"))
    slug = models.SlugField()
    common_project_phases = models.ManyToManyField(
        CommonProjectPhase,
        verbose_name=_("project phase"),
        related_name="document_templates",
    )

    def get_upload_subfolder(self):
        return ["document_templates", self.slug]

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
    image_template = models.BooleanField(
        verbose_name=_("image template"),
        default=False,
    )

    class Meta:
        verbose_name = _("document template")
        verbose_name_plural = _("document templates")

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        self.slug = slugify(self.name)
        return super().save(*args, **kwargs)


class ProjectDocumentDownloadLog(models.Model):
    """Logs a document download not including preview downloads"""

    created_at = models.DateTimeField(auto_now_add=True)
    project = models.ForeignKey(
        "Project",
        verbose_name=_("project"),
        related_name="document_download_log",
        on_delete=models.CASCADE,
    )
    document_template = models.ForeignKey(
        "DocumentTemplate",
        verbose_name=_("document template"),
        related_name="document_download_log",
        on_delete=models.CASCADE,
    )
    phase = models.ForeignKey(
        "CommonProjectPhase",
        verbose_name=_("phase"),
        related_name="document_download_log",
        on_delete=models.CASCADE,
    )
