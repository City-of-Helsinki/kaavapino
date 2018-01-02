import io

from django.http import HttpResponse
from docxtpl import DocxTemplate


def render_template(project, document_template):
    doc = DocxTemplate(document_template.file)
    doc.render(project.attribute_data)
    output = io.BytesIO()
    doc.save(output)
    return output.getvalue()


def get_document_response(project, document_template):
    output = render_template(project, document_template)
    response = HttpResponse(
        output, content_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document'
    )
    response['Content-Disposition'] = 'attachment; filename={}-{}.docx'.format(project.name, document_template.name)
    return response
