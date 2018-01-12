import json
import random

from django.core.serializers.json import DjangoJSONEncoder
from django.http import HttpResponseRedirect
from django.shortcuts import render
from django.urls import reverse
from django.views.generic.list import ListView

from projects.models import ProjectPhase, ProjectType

from .forms import create_section_form_class
from .models import Attribute, Project


class ProjectListView(ListView):
    model = Project
    template_name = 'project_list.html'


def generate_sections(project: Project=None):
    if project and project.phase:
        phase = project.phase
    else:
        phase = ProjectPhase.objects.get(index=0)

    sections = []
    for section in phase.sections.order_by('index'):
        section_data = {
            'section': section,
            'form_class': create_section_form_class(section),
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

    return json.loads(json.dumps(filtered_data, cls=DjangoJSONEncoder))


def project_edit(request, pk=None):
    if pk:
        project = Project.objects.get(pk=pk)
    else:
        project = Project()
        project.phase = ProjectPhase.objects.get(index=0)
        project.type = ProjectType.objects.first()

    sections = generate_sections(project)
    active_section = None

    for section in sections:
        attribute_identifiers = section['section'].get_attribute_identifiers()

        if 'save_section_{}'.format(section['section'].id) in request.POST:
            active_section = section['section'].id

            section['form'] = section['form_class'](request.POST)

            if section['form'].is_valid():
                if 'kaavahankkeen_nimi' in request.POST:
                    project.name = request.POST.get('kaavahankkeen_nimi')

                attribute_data = filter_data(attribute_identifiers, section['form'].cleaned_data)

                project.attribute_data.update(attribute_data)
                project.save()

                return HttpResponseRedirect(reverse('project-edit', kwargs={'pk': project.id}))
        else:
            if not active_section:
                active_section = section['section'].id

            section['form'] = section['form_class'](initial=filter_data(attribute_identifiers, project.attribute_data))

    context = {
        'project': project,
        'phases': ProjectPhase.objects.all(),
        'sections': sections,
        'active_section': active_section,
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
