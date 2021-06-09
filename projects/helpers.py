from projects.models import Attribute

def get_fieldset_path(attr, attribute_path=[]):
    if not attr.fieldsets.count():
        return attribute_path
    else:
        parent_fieldset = attr.fieldsets.first()
        return get_fieldset_path(
            parent_fieldset,
            [parent_fieldset] + attribute_path,
        )

def set_attribute_data(data, path, value):
    try:
        next_key = path[0].identifier
    except AttributeError:
        next_key = path[0]

    if len(path) > 1:
        if type(data) is dict:
            if not data.get(next_key):
                data[next_key] = []

            set_attribute_data(data.get(next_key), path[1:], value)
        elif type(data) is list:
            for __ in range(len(data), next_key+1):
                data.append({})

            set_attribute_data(data[next_key], path[1:], value)

    else:
        data[next_key] = value

def get_attribute_data(attribute_path, data):
    if len(attribute_path) == 0:
        return data

    return get_attribute_data(
        attribute_path[2:],
        data.get(attribute_path[0].identifier, [])[attribute_path[1]]
    )

def get_flat_attribute_data(data, flat={}):
    for key, val in data.items():
        flat[key] = flat.get(key, [])

        try:
            value_type = Attribute.objects.get(identifier=key).value_type
        except Attribute.DoesNotExist:
            value_type = None

        if type(val) is dict and value_type == Attribute.TYPE_FIELDSET:
            get_flat_attribute_data(val, flat)
        elif type(val) is list:
            try:
                for item in val:
                    get_flat_attribute_data(item, flat)
            except AttributeError:
                flat[key] += val
        else:
            flat[key].append(val)

    return flat
