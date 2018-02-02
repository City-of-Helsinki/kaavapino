import json
import random
from collections import OrderedDict

from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.views.generic import DetailView, ListView

from projects.models import ProjectPhase, ProjectType

from .exporting import get_document_response
from .forms import create_section_form_class
from .models import Attribute, DocumentTemplate, Project


class ProjectListView(ListView):
    model = Project
    template_name = 'project_list.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['own_projects'] = Project.objects.filter(user=self.request.user)

        return context


def generate_sections(project: Project=None, phase=None, for_validation=False):
    if not phase:
        phase = project.phase if project and project.phase else ProjectPhase.objects.get(
            project_type__name='asemakaava', index=0)

    sections = []
    for section in phase.sections.order_by('index'):
        section_data = {
            'section': section,
            'form_class': create_section_form_class(section, for_validation=for_validation, project=project),
            'form': None,
        }

        sections.append(section_data)

    return sections


def filter_data(identifiers, data):
    filtered_data = {
        key: value
        for key, value in data.items()
        if key in identifiers
    }
    return filtered_data


def filter_image_data(identifiers, data):
    image_identifiers = Attribute.objects.filter(value_type=Attribute.TYPE_IMAGE).values_list('identifier', flat=True)
    return filter_data(set(identifiers) & set(image_identifiers), data)


def project_edit(request, pk=None, phase_id=None):
    if pk:
        project = Project.objects.get(pk=pk)
    else:
        project = Project()
        project.phase = ProjectPhase.objects.get(project_type__name='asemakaava', index=0)
        project.type = ProjectType.objects.first()

    if phase_id:
        edit_phase = ProjectPhase.objects.get(pk=phase_id, project_type=project.type)
    else:
        edit_phase = project.phase

    validate = 'save_and_validate' in request.POST
    save = validate or 'save' in request.POST
    sections = generate_sections(project=project, phase=edit_phase, for_validation=validate)

    for section in sections:
        attribute_identifiers = section['section'].get_attribute_identifiers()
        form_class = section['form_class']

        if save:
            # basically POST

            if 'kaavahankkeen_nimi' in request.POST:
                project.name = request.POST.get('kaavahankkeen_nimi')

            # first build a form for cleaning all the posted values and save those in the project
            cleaning_form_class = create_section_form_class(section['section'], project=project)
            cleaning_form = cleaning_form_class(request.POST, request.FILES)
            cleaning_form.full_clean()

            attribute_data = filter_data(attribute_identifiers, cleaning_form.cleaned_data)
            project.update_attribute_data(attribute_data)
            project.save()

            if validate:
                # when validation is needed, build another form for it that will be returned in the context.
                # we must use initial instead of request.FILES because we need saved images, not ones loaded
                # in memory (because we need URLs for the images).
                image_data = filter_image_data(attribute_identifiers, project.get_attribute_data())
                section['form'] = form_class(request.POST, initial=image_data)
                section['form'].is_valid()
        else:
            # basically GET

            attribute_data = filter_data(attribute_identifiers, project.get_attribute_data())
            section['form'] = form_class(initial=attribute_data)

    if save and not validate:
        return HttpResponseRedirect(reverse('projects:edit', kwargs={
            'pk': project.id
        }))

    context = {
        'project': project,
        'edit_phase': edit_phase,
        'phases': ProjectPhase.objects.filter(project_type=project.type),
        'sections': sections,
    }

    return render(request, 'project_form.html', context=context)


def report_view(request):
    project_qs = Project.objects.filter(geometry__isnull=False, phase__isnull=False)
    project_qs = project_qs.select_related('phase')
    strategy_attr = Attribute.objects.get(identifier='strategiakytkenta')
    strategies = {x.identifier: x for x in strategy_attr.value_choices.all()}
    for project in project_qs:
        project.sqm2 = random.randint(1, 250)
        project_strategies = project.attribute_data.get('strategiakytkenta', [])
        project.strategies = json.dumps([strategies[x].value for x in project_strategies])
    context = dict(projects=project_qs)

    return render(request, 'report.html', context=context)


class ProjectCardView(DetailView):
    template_name = 'project_card.html'

    model = Project

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['phases'] = ProjectPhase.objects.filter(project_type=self.object.type)
        context['project'] = self.object
        context['project_attr'] = self.object.attribute_data
        return context


def project_change_phase(request, pk):
    project = Project.objects.get(pk=pk)
    next_phase = None

    try:
        # TODO: Determine the next phase better
        next_phase = ProjectPhase.objects.get(project_type=project.type, index=project.phase.index + 1)
    except ProjectPhase.DoesNotExist:
        pass

    context = {
        'project': project,
        'phases': ProjectPhase.objects.filter(project_type=project.type),
        'project_attr': project.attribute_data,
        'next_phase': next_phase,
    }

    if request.method == 'POST' and 'change-phase' in request.POST:
        context['sections'] = generate_sections(project=project, for_validation=True)

        for section in context['sections']:
            attribute_identifiers = section['section'].get_attribute_identifiers()
            attribute_data = filter_data(attribute_identifiers, project.get_attribute_data())
            image_data = filter_image_data(attribute_identifiers, attribute_data)
            form_class = section['form_class']

            # Use temporary form to get prepared values for the attribute_data
            tmp_form = form_class(attribute_data)
            for field in tmp_form.fields:
                attribute_data[field] = tmp_form[field].value()

            section['form'] = form_class(attribute_data, initial=image_data)

        context['is_valid'] = all([section['form'].is_valid() for section in context['sections']])

        # TODO: Check that the next_phase is valid and the user has suitable permissions
        if context['is_valid']:
            project.phase = next_phase
            project.save()

            return HttpResponseRedirect(reverse('projects:change-phase', kwargs={
                'pk': project.id
            }))

    return render(request, 'project_change_phase.html', context=context)


class DocumentCreateView(DetailView):
    model = Project
    context_object_name = 'project'
    template_name = 'document_create.html'

    @staticmethod
    def _get_context_data_for_documents_in_phase(documents, phase):
        return [
            {
                'enabled': True if document.name in ('OAS', 'Selostus') else False,  # TODO
                'obj': document,
            }
            for document in documents if document.project_phase == phase
        ]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        project = self.object
        documents = list(DocumentTemplate.objects.filter(project_phase__project_type=project.type))
        phases = list(project.type.phases.filter(document_templates__in=documents))
        documents_per_phase = OrderedDict()

        if project.phase and project.phase in phases:
            name = '{} (Nykyinen vaihe)'.format(project.phase.name)  # TODO translate
            documents_per_phase[name] = self._get_context_data_for_documents_in_phase(documents, project.phase)
            phases = [p for p in phases if p.pk != project.phase.pk]

        for phase in phases:
            documents_per_phase[phase.name] = self._get_context_data_for_documents_in_phase(documents, phase)

        context['documents_per_phase'] = documents_per_phase

        return context


def document_download_view(request, project_pk, document_pk):
    document_template = get_object_or_404(DocumentTemplate, pk=document_pk)
    project = get_object_or_404(Project, pk=project_pk)

    return get_document_response(project, document_template)
