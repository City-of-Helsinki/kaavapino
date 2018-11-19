from rest_framework.fields import JSONField


class AttributeDataField(JSONField):
    def __init__(self, method_name=None, **kwargs):
        self.method_name = method_name
        super().__init__(**kwargs)

    def bind(self, field_name, parent):
        default_method_name = "get_{field_name}".format(field_name=field_name)
        assert self.method_name != default_method_name, (
            "It is redundant to specify `%s` on SerializerMethodField '%s' in "
            "serializer '%s', because it is the same as the default method name. "
            "Remove the `method_name` argument."
            % (self.method_name, field_name, parent.__class__.__name__)
        )

        # The method name should default to `get_{field_name}`.
        if self.method_name is None:
            self.method_name = default_method_name

        super().bind(field_name, parent)

    def get_attribute(self, obj):
        # We pass the object instance onto `to_representation`,
        # not just the field attribute.
        return obj

    def to_representation(self, instance):
        method = getattr(self.parent, self.method_name)
        return super().to_representation(method(instance))
