from django import forms

from .models import Attribute

FIELD_TYPES = {
    Attribute.TYPE_SHORT_STRING: (forms.CharField, {}),
    Attribute.TYPE_LONG_STRING: (forms.CharField, {'widget': forms.Textarea}),
    Attribute.TYPE_INTEGER: (forms.IntegerField, {}),
    Attribute.TYPE_BOOLEAN: (forms.BooleanField, {'required': False}),
    Attribute.TYPE_DATE: (forms.DateField, {}),
}


def create_section_form_class(section):
    form_properties = {}

    for section_attribute in section.projectphasesectionattribute_set.order_by('index'):
        attribute = section_attribute.attribute

        extra = {
            'required': section_attribute.required and not section_attribute.generated,
            'disabled': section_attribute.generated,
        }
        value_choices = attribute.value_choices.all()

        if value_choices.exists():
            field_class = forms.ChoiceField
            extra['choices'] = [['', '---']] + list(value_choices.values_list('identifier', 'value'))
        else:
            (field_class, field_kwargs) = FIELD_TYPES.get(attribute.value_type)
            extra.update(field_kwargs)

        form_properties[attribute.identifier] = field_class(label=attribute.name, **extra)

    return type('SectionForm', (forms.Form,), form_properties)
