from django import template

register = template.Library()


@register.filter
def index(l: list, i: str):
    return l[int(i)]
