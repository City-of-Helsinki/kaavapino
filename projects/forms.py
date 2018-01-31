from django.contrib.gis import forms

from .models import Attribute
from users.models import User

from .widgets import MapboxWidget

FIELD_TYPES = {
    Attribute.TYPE_SHORT_STRING: (forms.CharField, {}),
    Attribute.TYPE_LONG_STRING: (forms.CharField, {'widget': forms.Textarea}),
    Attribute.TYPE_INTEGER: (forms.IntegerField, {}),
    Attribute.TYPE_BOOLEAN: (forms.BooleanField, {'required': False}),
    Attribute.TYPE_DATE: (forms.DateField, {}),
    Attribute.TYPE_GEOMETRY: (forms.MultiPolygonField, {'widget': MapboxWidget}),
}


def create_section_form_class(section, for_validation=False, project=None):
    form_properties = {}

    for section_attribute in section.projectphasesectionattribute_set.order_by('index'):
        attribute = section_attribute.attribute

        extra = {
            'required': section_attribute.required and not section_attribute.generated and for_validation,
            'disabled': section_attribute.generated,
            'help_text': attribute.help_text,
        }

        if attribute.value_type == Attribute.TYPE_USER:
            full_names = [u.get_full_name() for u in User.objects.all()]
            value_choices = [(n, n) for n in full_names]

            if project:
                # if the field already has a value that is not from current actual users (from an import for example)
                # add it to choices to allow saving it.
                original_value = project.attribute_data.get(attribute.identifier)
                if original_value and original_value not in full_names:
                    value_choices = [(original_value, original_value)] + value_choices
        else:
            value_choices = list(attribute.value_choices.values_list('identifier', 'value'))

        if value_choices or attribute.value_type == Attribute.TYPE_USER:
            field_class = forms.MultipleChoiceField if attribute.multiple_choice else forms.ChoiceField
            extra['choices'] = [('', '---')] + value_choices
        else:
            try:
                (field_class, field_kwargs) = FIELD_TYPES[attribute.value_type]
            except KeyError:
                continue
            extra.update(field_kwargs)

        form_properties[attribute.identifier] = field_class(label=attribute.name, **extra)

    return type('SectionForm', (forms.Form,), form_properties)
