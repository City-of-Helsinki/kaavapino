from projects.models import Attribute


def _is_attribute_required(attribute: Attribute):
    if not attribute.generated:
        return attribute.required
    else:
        return False

def _set_fieldset_path(fieldset_content, path, parent_obj, i, identifier, value):
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


    # TODO multi-level fieldset image uploads not needed/supported for now
    if False and i < len(path) - 1:
        if next_obj is None:
            if fieldset_content:
                parent_obj[parent_id][index] = {**fieldset_content}
            else:
                parent_obj[parent_id][index] = {}

            next_obj = parent_obj[parent_id][index]

        # TODO Handle fieldset_content within multi-level fieldsets later
        _set_fieldset_path(
            None,
            path,
            next_obj,
            i+1,
            identifier,
            value
        )

    else:
        if next_obj is None:
            if fieldset_content:
                parent_obj[parent_id][index] = {
                    **fieldset_content,
                    identifier: value,
                }
            else:
                parent_obj[parent_id][index] = {identifier: value}
        else:
            for k, v in fieldset_content.items():
                next_obj[k] = v

            next_obj[identifier] = value
