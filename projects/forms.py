from django.contrib.auth import get_user_model
from django.contrib.gis import forms
from django.forms import ChoiceField

from .models import Attribute
from .widgets import MapboxWidget

FIELD_TYPES = {
    Attribute.TYPE_SHORT_STRING: (forms.CharField, {}),
    Attribute.TYPE_LONG_STRING: (forms.CharField, {'widget': forms.Textarea}),
    Attribute.TYPE_INTEGER: (forms.IntegerField, {}),
    Attribute.TYPE_BOOLEAN: (forms.BooleanField, {'required': False}),
    Attribute.TYPE_DATE: (forms.DateField, {}),
    Attribute.TYPE_GEOMETRY: (forms.MultiPolygonField, {'widget': MapboxWidget}),
}


def _generate_form_user_id(user):
    return '__' + str(user.id)


class UserChoiceField(ChoiceField):
    def prepare_value(self, value):
        if isinstance(value, get_user_model()):
            value = _generate_form_user_id(value)
        return super().prepare_value(value)

    def clean(self, value):
        value = super().clean(value)
        if value.startswith('__'):
            value = get_user_model().objects.get(id=int(value[2:]))
        return value


def _get_field_class_and_extra_for_user(attribute, project):
    value_choices = [(_generate_form_user_id(u), u.get_full_name()) for u in get_user_model().objects.all()]

    if project:
        # if the field already has a value that is not from current actual users (from an import for example)
        # add it to choices to allow saving it.
        original_value = project.attribute_data.get(attribute.identifier)
        if isinstance(original_value, str):
            value_choices = [(original_value, original_value)] + value_choices

    field_class = UserChoiceField
    extra = {'choices': [('', '---')] + value_choices}

    return field_class, extra


def _get_field_class_and_extra(attribute):
    value_choices = attribute.value_choices.all()

    if value_choices:
        if attribute.multiple_choice:
            field_class = forms.ModelMultipleChoiceField
        else:
            field_class = forms.ModelChoiceField
        extra = {'to_field_name': 'identifier', 'queryset': value_choices}
    else:
        try:
            (field_class, extra) = FIELD_TYPES[attribute.value_type]
        except KeyError:
            return None, {}

    return field_class, extra


def create_section_form_class(section, for_validation=False, project=None):
    form_properties = {}

    for section_attribute in section.projectphasesectionattribute_set.order_by('index'):
        attribute = section_attribute.attribute

        if attribute.value_type == Attribute.TYPE_USER:
            field_class, extra = _get_field_class_and_extra_for_user(attribute, project)
        else:
            field_class, extra = _get_field_class_and_extra(attribute)

        if not field_class:
            continue

        if for_validation and not section_attribute.generated and attribute.value_type != Attribute.TYPE_BOOLEAN:
            extra['required'] = section_attribute.required
        else:
            extra['required'] = False

        extra.update({
            'disabled': section_attribute.generated,
            'help_text': attribute.help_text,
        })

        form_properties[attribute.identifier] = field_class(label=attribute.name, **extra)

    return type('SectionForm', (forms.Form,), form_properties)
