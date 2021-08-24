import re
import requests

from django.conf import settings
from django.core.cache import cache
from rest_framework import status
from rest_framework.response import Response

from users.helpers import get_graph_api_access_token
from users.serializers import PersonnelSerializer


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

def get_flat_attribute_data(data, flat):
    from projects.models import Attribute
    for key, val in data.items():
        flat[key] = flat.get(key, [])

        try:
            value_type = Attribute.objects.get(identifier=key).value_type
        except Attribute.DoesNotExist:
            value_type = None

        if type(val) is list and value_type == Attribute.TYPE_FIELDSET:
            for item in val:
                get_flat_attribute_data(item, flat)
        elif type(val) is list:
            flat[key] += val
        else:
            flat[key].append(val)

    return flat

def set_kaavoitus_api_data_in_attribute_data(attribute_data):
    from projects.models import Attribute
    external_data_attrs = Attribute.objects.filter(
        data_source__isnull=False,
    )

    leaf_node_attrs = external_data_attrs.filter(
        data_source__isnull=False,
    ).exclude(
        value_type=Attribute.TYPE_FIELDSET,
    )

    flat_attribute_data = get_flat_attribute_data(attribute_data, {})

    def build_request_paths(attr):
        returns = {}
        if attr.key_attribute:
            key_values = flat_attribute_data.get(
                attr.key_attribute.identifier, []
            )
        else:
            parent_attr = Attribute.objects.get(
                identifier=attr.key_attribute_path.split(".")[0]
            )
            key_values = flat_attribute_data.get(
                parent_attr.key_attribute.identifier, []
            )

        # Remove hyphens if the key is a kiinteistotunnus,
        # geoserver does not support the hyphened form
        for value in key_values:
            if attr.data_source in [
                Attribute.SOURCE_FACTA, Attribute.SOURCE_GEOSERVER
            ]:
                pk = "".join(str(value).split("-"))
            else:
                pk = str(value)

            path = attr.data_source.replace("<pk>", pk)
            returns[value] = f"{settings.KAAVOITUS_API_BASE_URL}{path}"

        return returns

    fetched_data = {
        attr: build_request_paths(attr)
        for attr in external_data_attrs.exclude(
            data_source=Attribute.SOURCE_PARENT_FIELDSET,
        )
    }

    for attr, urls in fetched_data.items():
        for key, value in urls.items():
            url = value
            if cache.get(url) is not None:
                response = cache.get(url)
            else:
                response = requests.get(
                    url,
                    headers={"Authorization": f"Token {settings.KAAVOITUS_API_AUTH_TOKEN}"},
                )
                if response.status_code == 200:
                    cache.set(url, response, 28800)
                else:
                    cache.set(url, response, 180)

            if response.status_code == 200:
                fetched_data[attr][key] = response.json()
            else:
                fetched_data[attr][key] = None

    def get_deep(source, keys, default=None):
        if not keys:
            return source

        if type(keys) is str:
            keys = keys.split(".")

        if type(source) is not dict:
            return default

        if len(keys) > 1:
            return get_deep(
                source.get(keys[0], None),
                keys[1:],
                default,
            )
        else:
            return source.get(keys[0], None)

    def get_in_attribute_data(attribute_path, data):
        if len(attribute_path) == 2:
            data = data.get(attribute_path[0].identifier, [])
            if type(data) is list:
                return [
                    item.get(attribute_path[1].identifier)
                    for item in data
                ]
            else:
                return [data.get(attribute_path[1].identifier)]

        return get_in_attribute_data(
            attribute_path[2:],
            data.get(attribute_path[0].identifier, [])[attribute_path[1][0]]
        )

    leaf_paths = []

    def get_branch_paths(data, solved_path, remaining_path, saved_keys={}, first_run=True):
        if first_run:
            saved_keys = {}

        if not remaining_path:
            leaf_paths.append([solved_path] if first_run else solved_path)
            return

        data_source_key = None
        data_source_keys = None
        current = remaining_path[0]
        if current.data_source != Attribute.SOURCE_PARENT_FIELDSET \
            and current.key_attribute:
            data_source_keys = get_in_attribute_data(
                solved_path + [current, current.key_attribute],
                attribute_data,
            )
            data_items = fetched_data.get(current)
            item_count = len(data_items)
        elif current.data_source != Attribute.SOURCE_PARENT_FIELDSET \
            and current.key_attribute_path:
            data_source_keys = saved_keys.get(current.key_attribute_path)
            data_items = fetched_data.get(current)
            item_count = len(data_source_keys)
        elif current.key_attribute_path:
            data_source_key = saved_keys.get(current.key_attribute_path[0])
            data_items = fetched_data.get(current)
            item_count = 1
        else:
            data_items = data
            if type(data_items) is list:
                item_count = len(data_items)
            elif not data_items:
                item_count = 0
            else:
                item_count = 1

        fs_children_counter = 0
        for i in range(0, item_count):
            new_saved_keys = saved_keys
            if data_source_key:
                data_item = data_items.get(data_source_key)
                data_index = None
                pass
            elif current.key_attribute_path:
                data_item = data_items.get(data_source_keys[i])
                data_index = data_source_keys[i]

                if not data_item:
                    continue

                data_item = get_deep(data_item, current.data_source_key)
            elif data_source_keys:
                data_index = data_source_keys[i]
                data_item = get_deep(
                    data_items,
                    current.data_source_key,
                ).get(data_source_keys[i])
                new_saved_keys[
                    f"{current.identifier}.{current.key_attribute.identifier}"
                ] = [data_index]
            else:
                data_index = None
                data_item = get_deep(data, current.data_source_key)

            if current.value_type == Attribute.TYPE_FIELDSET:
                if type(data_item) is list:
                    for j in range(0, len(data_item)):
                        get_branch_paths(
                            data_item,
                            solved_path + [current] + [(
                                fs_children_counter+j,
                                data_index,
                                j,
                            )],
                            remaining_path[1:],
                            new_saved_keys,
                            first_run=False,
                        )

                    fs_children_counter += len(data_item)

                else:
                    get_branch_paths(
                        data_item,
                        solved_path + [current] + [(i, data_index, None)],
                        remaining_path[1:],
                        new_saved_keys,
                        first_run=False,
                    )
                    fs_children_counter += 1
            else:
                get_branch_paths(
                    data_item,
                    solved_path + [current],
                    remaining_path[1:],
                    new_saved_keys,
                    first_run=False,
                )

    for attr in leaf_node_attrs:
        fieldset_path = get_fieldset_path(attr) + [attr]

        get_branch_paths(
            fetched_data,
            [],
            fieldset_path,
        )

    def get_in_fetched_data(data, attribute_path):
        if not attribute_path:
            return data

        current = attribute_path[0]

        if type(current) == Attribute and current.key_attribute_path:
            data = fetched_data.get(current).get(attribute_path[1][1])

            if current.data_source_key:
                data = get_deep(data, current.data_source_key.split("."))

            if type(data) is list:
                data = data[attribute_path[1][2]]

            return get_in_fetched_data(
                data,
                attribute_path[2:],
            )

        if type(data) is dict:
            return get_in_fetched_data(
                get_deep(data, current.data_source_key),
                attribute_path[1:],
            )
        elif type(data) is list:
            return get_in_fetched_data(
                data[current[0]],
                attribute_path[1:],
            )
        # Reaching this means improper attribute configuration; raise exception?
        else:
            return None

    def set_in_attribute_data(data, path, value):
        try:
            next_key = path[0].identifier
        except AttributeError:
            next_key = path[0][0]

        if len(path) > 1:
            if type(data) is dict:
                if not data.get(next_key):
                    data[next_key] = []

                set_in_attribute_data(data.get(next_key), path[1:], value)
            elif type(data) is list:
                for __ in range(len(data), next_key+1):
                    data.append({})

                set_in_attribute_data(data[next_key], path[1:], value)

        else:
            data[next_key] = value

    for path in leaf_paths:
        # leaf node may have special rules; handle it separately
        fetched_data_entry = fetched_data[path[0]][path[1][1]]
        value = get_in_fetched_data(
            fetched_data_entry,
            path[2:-1],
        )

        if path[-1].key_attribute_path:
            (pk_index, __, __) = path[
                path.index(Attribute.objects.get(
                    identifier=path[-1].key_attribute_path.split(".")[0]
                )) + 1
            ]
            value = fetched_data.get(path[-1]).get(
                list(fetched_data.get(path[-1]).keys())[pk_index]
            )

        # Split on "." until we reach a "{"
        [dsk_path, dsk_rule] = (
            path[-1].data_source_key.split("{", 1) + [None]
        )[0:2]

        if "." in dsk_path and dsk_rule:
            data_source_keys = [
                item for item in dsk_path.split(".") + ["{"+dsk_rule]
                if item
            ]
        elif "." in dsk_path:
            data_source_keys = [
                item for item in dsk_path.split(".")
                if item
            ]
        elif dsk_rule:
            # put this back together after all
            data_source_keys = [dsk_path+"{"+dsk_rule]
        else:
            data_source_keys = [dsk_path]


        if len(data_source_keys) > 1:
            value = get_deep(value, data_source_keys[:-1])

        # The last key supports these formats:
        # - plain key name ("key_to_data")
        # - multiple keys whose values will be combined into one string
        #   ("some_key;another_key")
        # - if-else rules
        #   ("{True|False|123|abc if some_key ==|!=|in|not in value else True|False|123|abc}")
        #   where some_key can be nested (...if some_key.another_key else...)
        #   and if/else value foo,bar will be parsed as ["foo", "bar"]
        #   if operator is "in" or "not in"
        #   note: a list of dicts will result in adding the results together
        # - dictionary ("some_key:{"key_1": "value 1", "key_2": "value_2"}")
        last_key = data_source_keys[-1]
        if ";" in last_key:
            value = " ".join([
                str(value.get(key))
                for key in data_source_keys[-1].split(";")
                if value.get(key)
            ])
        elif last_key[0] != "{" and last_key[-1] == "}":
            last_key, dictionary = last_key.split(":", 1)
            dictionary = re.split(r"(?<=\")[,:]\s", dictionary[1:-1])
            dict_keys = dictionary[0::2]
            dict_vals = dictionary[1::2]
            dictionary = {
                key[1:-1]: val[1:-1]
                for key, val in zip(dict_keys, dict_vals)
            }
            value = dictionary.get(value.get(last_key))
        elif last_key[0] == "{" and last_key[-1] == "}":
            last_key = last_key[1:-1]
            if_value, last_key = last_key.split(" if ", 1)
            last_key, else_value = last_key.split(" else ", 1)
            last_key, equals = (last_key.split(" == ", 1) + [None])[0:2]
            last_key, not_equals = (last_key.split(" != ", 1) + [None])[0:2]
            last_key, not_in = (last_key.split(" not in ", 1) + [None])[0:2]
            last_key, is_in = (last_key.split(" in ", 1) + [None])[0:2]

            def parse_value(val):
                if val == "True":
                    return True
                elif val == "False":
                    return False
                else:
                    try:
                        return int(val)
                    except ValueError:
                        return val

            if_value = parse_value(if_value)
            else_value = parse_value(else_value)

            def get_result(value):
                if value is None and type(if_value) is bool:
                    # Hard-coded special case because property_owner_municipality
                    # returns null and there's nothing we can do about it.
                    # Think of a better way to solve this problem if this
                    # solution ever clashes with some future rule.
                    return False
                elif equals:
                    return if_value if value == equals else else_value
                elif not_equals:
                    return if_value if value != not_equals else else_value
                elif not_in:
                    return if_value \
                        if value not in not_in.split(",") \
                        else else_value
                elif is_in:
                    return if_value \
                        if value in is_in.split(",") \
                        else else_value

            if type(value) is list:
                values = [
                    get_deep(item, last_key.split("."))
                    for item in value
                ]
                value = bool(sum([
                    get_result(value) for value in values
                ]))
            else:
                value = get_result(get_deep(value, last_key.split(".")))

        else:
            value = value.get(data_source_keys[-1])

        set_in_attribute_data(attribute_data, path, value)

def get_ad_user(id):
    url = f"{settings.GRAPH_API_BASE_URL}/v1.0/users/{id}?$select=companyName,givenName,id,jobTitle,mail,mobilePhone,officeLocation,surname"
    response = cache.get(url)
    if not response:
        token = get_graph_api_access_token()
        if not token:
            return Response(
                "Cannot get access token",
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
        response = requests.get(
            url, headers={"Authorization": f"Bearer {token}"}
        )

        if not response:
            return None

        cache.set(url, response, 60)

    return response.json()

def set_ad_data_in_attribute_data(attribute_data):
    from projects.models import Attribute
    paths = []

    def add_paths(solved_path, remaining_path, parent_data):
        if remaining_path[0].value_type != Attribute.TYPE_FIELDSET:
            paths.append(solved_path + [remaining_path[0]])
            return

        children = parent_data.get(remaining_path[0].identifier, [])

        for i, child in enumerate(children):
            add_paths(
                solved_path + [remaining_path[0], i],
                remaining_path[1:],
                child,
            )

    def get_in_personnel_data(id, key):
        user = get_ad_user(id)
        return PersonnelSerializer(user).data.get(key)

    for attr in Attribute.objects.filter(
        ad_key_attribute__isnull=False,
        ad_data_key__isnull=False,
    ):
        fieldset_path = get_fieldset_path(attr)
        add_paths([], fieldset_path+[attr], attribute_data)

    for path in paths:
        attr = path[-1]
        data = get_attribute_data(path[:-1], attribute_data)
        user_id = data.get(attr.ad_key_attribute.identifier)

        if not user_id:
            continue

        value = get_in_personnel_data(user_id, attr.ad_data_key)

        if value:
            set_attribute_data(attribute_data, path, value)
