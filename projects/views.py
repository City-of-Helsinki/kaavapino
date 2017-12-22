from django.shortcuts import render


def index(request, path='index'):
    template_filename = '{}.html'.format(path)

    return render(request, template_filename)
