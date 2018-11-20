from projects.models import Attribute


def _is_attribute_required(attribute: Attribute):
    if attribute.value_type != Attribute.TYPE_BOOLEAN and not attribute.generated:
        return attribute.required
    else:
        return False
