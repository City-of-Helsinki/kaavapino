import json

from django import forms
from django.core.serializers.json import DjangoJSONEncoder

from .models import Attribute, Project, ProjectType

FIELD_TYPES = {
    Attribute.TYPE_SHORT_STRING: (forms.CharField, {}),
    Attribute.TYPE_LONG_STRING: (forms.CharField, {'widget': forms.Textarea}),
    Attribute.TYPE_INTEGER: (forms.IntegerField, {}),
    Attribute.TYPE_BOOLEAN: (forms.BooleanField, {'required': False}),
    Attribute.TYPE_DATE: (forms.DateField, {}),
}


class ProjectForm(forms.ModelForm):
    class Meta:
        model = Project
        fields = []

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        for attribute in Attribute.objects.prefetch_related('value_choices'):
            extra = {}
            value_choices = attribute.value_choices.all()

            if value_choices.exists():
                field_class = forms.ChoiceField
                extra['choices'] = [['', '---']] + list(value_choices.values_list('identifier', 'value'))
            else:
                (field_class, field_kwargs) = FIELD_TYPES.get(attribute.value_type)
                extra.update(field_kwargs)

            self.fields[attribute.identifier] = field_class(label=attribute.name, **extra)

    def save(self, commit=True):
        instance = super().save(commit=False)

        attribute_identifiers = Attribute.objects.values_list('identifier', flat=True)

        attribute_data = {
            key: value
            for key, value in self.cleaned_data.items()
            if key in attribute_identifiers
        }
        instance.attribute_data = json.loads(json.dumps(attribute_data, cls=DjangoJSONEncoder))

        # TODO
        instance.name = str(instance.attribute_data['kaavahankkeen_nimi'])
        instance.type, _ = ProjectType.objects.get_or_create(name='asemakaava')

        if commit:
            instance.save()

        return instance
