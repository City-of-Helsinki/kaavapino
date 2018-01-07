import random
import json
from django.http import HttpResponse
from django.shortcuts import render
from projects.models import Project, Attribute


def index(request, path='index'):
    if 'favicon.ico' in path:
        return HttpResponse('')

    template_filename = '{}.html'.format(path)
    project_qs = Project.objects.filter(geometry__isnull=False, phase__isnull=False)
    project_qs = project_qs.select_related('phase')
    strategy_attr = Attribute.objects.get(identifier='strategiakytkenta')
    strategies = {x.identifier: x for x in strategy_attr.value_choices.all()}
    for project in project_qs:
        project.sqm2 = random.randint(1, 250)
        project_strategies = project.attribute_data.get('strategiakytkenta', [])
        project.strategies = json.dumps([strategies[x].value for x in project_strategies])
    context = dict(projects=project_qs)

    return render(request, template_filename, context=context)
