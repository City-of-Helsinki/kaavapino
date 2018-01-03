from django.utils.text import slugify


def create_identifier(text):
    return slugify(text).replace('-', '_')
