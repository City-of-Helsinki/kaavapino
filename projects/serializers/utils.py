from projects.models import Attribute


def _is_attribute_required(attribute: Attribute):
    if not attribute.generated:
        return attribute.required
    else:
        return False

def _set_fieldset_path(path, parent_obj, i, identifier, value):
    parent_id = path[i]["parent"].identifier
    index = path[i]["index"]

    try:
        next_obj = parent_obj[parent_id][index]
    except KeyError:
        parent_obj[parent_id] = [None] * (index + 1)
        parent_obj[parent_id][index] = {}
        next_obj = parent_obj[parent_id][index]
    except IndexError:
        parent_obj[parent_id] += [None] * (index + 1 - len(parent_obj[parent_id]))
        next_obj = parent_obj[parent_id][index]

    if i < len(path) - 1:
        if next_obj is None:
            print("jäljellä kamaa, täyetään tyhjä kohta ja jatketaan")
            parent_obj[parent_id][index] = {}
            next_obj = parent_obj[parent_id][index]

        _set_fieldset_path(path, next_obj, i+1, identifier, value)

    else:
        if next_obj is None:
            parent_obj[parent_id][index] = {identifier: value}
        else:
            next_obj[identifier] = value
