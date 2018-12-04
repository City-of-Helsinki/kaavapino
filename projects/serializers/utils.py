from projects.models import Attribute


def _is_attribute_required(attribute: Attribute):
    if not attribute.generated:
        return attribute.required
    else:
        return False
