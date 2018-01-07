import random
from django.http import HttpResponse
from django.shortcuts import render
from projects.models import Project


def index(request, path='index'):
    if 'favicon.ico' in path:
        return HttpResponse('')

    template_filename = '{}.html'.format(path)
    project_qs = Project.objects.filter(geometry__isnull=False, phase__isnull=False)
    project_qs = project_qs.select_related('phase')
    for project in project_qs:
        project.sqm2 = random.randint(1, 250)
    context = dict(projects=project_qs)

    return render(request, template_filename, context=context)
