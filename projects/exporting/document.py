import io

from django.http import HttpResponse
from django.utils import timezone
from docxtpl import DocxTemplate

from ..models.utils import create_identifier


def render_template(project, document_template):
    doc = DocxTemplate(document_template.file)
    doc.render(project.attribute_data)
    output = io.BytesIO()
    doc.save(output)
    return output.getvalue()


def get_document_response(project, document_template, filename=None):
    if filename is None:
        filename = '{}-{}-{}'.format(create_identifier(project.name), document_template.name, timezone.now().date())

    output = render_template(project, document_template)
    response = HttpResponse(
        output, content_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document'
    )
    response['Content-Disposition'] = 'attachment; filename={}.docx'.format(filename)
    return response
