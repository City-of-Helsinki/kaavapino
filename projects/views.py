from django.http import HttpResponse
from django.shortcuts import render


def index(request, path='index'):
    if 'favicon.ico' in path:
        return HttpResponse('')

    template_filename = '{}.html'.format(path)

    return render(request, template_filename)
