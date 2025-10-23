from collections import OrderedDict
import re
import requests
import json
import logging
import copy

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.exceptions import ValidationError
from requests import Timeout
from rest_framework import status
from rest_framework.renderers import JSONRenderer
from rest_framework.response import Response
from datetime import datetime

from users.helpers import get_graph_api_access_token
from users.serializers import PersonnelSerializer

log = logging.getLogger(__name__)

def get_fieldset_path(attr, attribute_path=[], cached=True, orig_attr=None):
    orig_attr = orig_attr or attr
    cache_key = f'projects.helpers.get_fieldset_path.{orig_attr.identifier}'
    if cached:
        cache_value = cache.get(cache_key)
        if cache_value:
            return cache_value

    if not attr.fieldsets.count():
        cache.set(cache_key, attribute_path, None)
        return attribute_path
    else:
        parent_fieldset = attr.fieldsets.first()
        return get_fieldset_path(
            parent_fieldset,
            [parent_fieldset] + attribute_path,
            orig_attr = orig_attr,
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

    if len(attribute_path) == 1:
        return data.get(attribute_path[0].identifier)

    return get_attribute_data(
        attribute_path[2:],
        data.get(attribute_path[0].identifier, [])[attribute_path[1]]
    )

def get_flat_attribute_data(data, flat, first_run=True, flat_key=None, value_types={}):
    from projects.models import Attribute
    if first_run:
        id = data.get("pinonumero")
        cache_key = 'projects.helpers.get_flat_attribute_data'
        flats = cache.get_or_set(cache_key, OrderedDict())
        flat_key = str(data)
        cached_flat = flats.get((id, flat_key))

        if cached_flat:
            flats.move_to_end((id, flat_key), last=True)
            cache.set(cache_key, flats, None)
            return cached_flat

        value_types = {a.identifier: a.value_type for a in Attribute.objects.all()}

    for key, val in data.items():
        flat[key] = flat.get(key, [])
        value_type = value_types.get(key, None)

        if type(val) is list and value_type in [Attribute.TYPE_FIELDSET, Attribute.TYPE_INFO_FIELDSET]:
            for item in val:
                get_flat_attribute_data(
                    item, flat, first_run=False, flat_key=flat_key, value_types=value_types
                )
        elif type(val) is list:
            flat[key] += val
        else:
            flat[key].append(val)

    if first_run:
        for key, item in [
            (k, v) for (k, v) in flats.items() if k[0] == id
        ]:
            flats.move_to_end(key, last=False)
            flats.popitem(last=False)

        # max cache size
        if len(flats) > 500:
            flats.popitem(last=False)

        flats[(id, flat_key)] = flat
        flats.move_to_end((id, flat_key), last=False)
        cache.set(cache_key, flats, None)

    return flat


def update_paikkatieto(attribute_data, use_cached=True):
    identifier = attribute_data.get("hankenumero", None)
    if not identifier:
        return

    url = f"{settings.KAAVOITUS_API_BASE_URL}/hel/v1/paikkatieto/{identifier}"

    paikkatieto_data = cache.get(url) if use_cached else None
    if not paikkatieto_data:
        try:
            response = requests.get(
                url,
                headers={"Authorization": f"Token {settings.KAAVOITUS_API_AUTH_TOKEN}"},
                timeout=30
            )
            if response.status_code == 200:
                paikkatieto_data = response.json()
                cache.set(url, paikkatieto_data, None)  # Refreshed automatically with task
            else:
                cache.set(url, "error", 900)  # 15 minutes
        except Timeout:
            log.error("Request timed out for url: {}".format(url))
            cache.set(url, "error", 3600)  # 1 hour

    if paikkatieto_data and paikkatieto_data != "error":
        attribute_data.update(paikkatieto_data)


def set_kaavoitus_api_data_in_attribute_data(attribute_data, use_cached=True):

    from projects.models import Attribute
    external_data_attrs = Attribute.objects.filter(
        data_source__isnull=False,
    ).select_related("key_attribute")

    leaf_node_attrs = external_data_attrs.filter(
        data_source__isnull=False,
    ).exclude(
        value_type__in=[Attribute.TYPE_FIELDSET, Attribute.TYPE_INFO_FIELDSET],
    ).select_related("key_attribute")

    flat_attribute_data = get_flat_attribute_data(attribute_data, {})
    update_paikkatieto(attribute_data, use_cached)

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
        ) if attr is not None
    }

    for attr, urls in fetched_data.items():
        for key, url in urls.items():
            data = cache.get(url) if use_cached else None
            if not data:
                try:
                    response = requests.get(
                        url,
                        headers={"Authorization": f"Token {settings.KAAVOITUS_API_AUTH_TOKEN}"},
                        timeout=180
                    )
                except Timeout:
                    log.error("Request timed out for url: {}".format(url))
                    response = Response(
                        data="Kaavoitus-api did not return a response in time.",
                        status=status.HTTP_408_REQUEST_TIMEOUT
                    )

                if response.status_code == 200:
                    data = response.json()
                    cache.set(url, data, None)  # Refreshed periodically with automated task
                elif response.status_code in [400, 404, 408]:
                    cache.set(url, "error", 86400)  # 24 hours
                else:
                    cache.set(url, "error", 900)  # 15 minutes

            if data and data != "error":
                fetched_data[attr][key] = data
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

            if current.value_type in [Attribute.TYPE_FIELDSET, Attribute.TYPE_INFO_FIELDSET]:
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
                if value and value.get(key)
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
    url = f"{settings.GRAPH_API_BASE_URL}/v1.0/users/{id}" \
          "?$select=companyName,givenName,id,jobTitle,mail,mobilePhone,businessPhones,officeLocation,surname"
    try:
        ad_user_data = cache.get(url)
    except TypeError:
        return None

    if not ad_user_data:
        token = get_graph_api_access_token()
        if not token:
            return Response(
                "Cannot get access token",
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
        response = requests.get(
            url, headers={"Authorization": f"Bearer {token}"}
        )
        if response:
            ad_user_data = response.json()
            cache.set(url, ad_user_data, 3600)

    return ad_user_data

def _add_paths(paths, solved_path, remaining_path, parent_data):
    from projects.models import Attribute
    if remaining_path[0].value_type not in [Attribute.TYPE_FIELDSET, Attribute.TYPE_INFO_FIELDSET]:
        paths.append(solved_path + [remaining_path[0]])
        return

    children = parent_data.get(remaining_path[0].identifier, [])

    for i, child in enumerate(children):
        _add_paths(
            paths,
            solved_path + [remaining_path[0], i],
            remaining_path[1:],
            child,
        )

def get_in_personnel_data(id, key, is_kaavapino_user):
    User = get_user_model()

    if is_kaavapino_user:
        try:
            id = id.uuid
        except AttributeError:
            pass

        try:
            id = User.objects.get(uuid=id).ad_id
        except (User.DoesNotExist, ValidationError):
            return None

    user = get_ad_user(id)
    return PersonnelSerializer(user).data.get(key)


def set_geoserver_data_in_attribute_data(attribute_data):
    identifier = attribute_data.get("hankenumero", None)
    if not identifier:
        return

    url = f"{settings.KAAVOITUS_API_BASE_URL}/geoserver/v1/suunnittelualue/{identifier}"

    geoserver_data = cache.get(url)
    if not geoserver_data:
        try:
            response = requests.get(
                url,
                headers={"Authorization": f"Token {settings.KAAVOITUS_API_AUTH_TOKEN}"},
                timeout=15
            )
            if response.status_code == 200:
                geoserver_data = response.json()
                cache.set(url, geoserver_data, 86400)  # 1 day
            else:
                cache.set(url, "error", 3600)  # 1 hour
        except Timeout:
            log.error("Request timed out for url: {}".format(url))
            cache.set(url, "error", 3600)  # 1 hour

    if geoserver_data and geoserver_data != "error":
        for geo_attr in list(geoserver_data.keys()):
            # Prioritize manually set values
            if attribute_data.get(geo_attr, False):
                geoserver_data.pop(geo_attr, None)
        attribute_data.update(geoserver_data)


def set_ad_data_in_attribute_data(attribute_data):
    from projects.models import Attribute
    paths = []

    attributes = Attribute.objects.filter(
        ad_key_attribute__isnull=False,
        ad_data_key__isnull=False,
    ).select_related("ad_key_attribute").prefetch_related("fieldsets")

    for attr in attributes:
        fieldset_path = get_fieldset_path(attr)
        _add_paths(paths, [], fieldset_path+[attr], attribute_data)

    for path in paths:
        attr = path[-1]
        data = get_attribute_data(path[:-1], attribute_data)
        user_id = data.get(attr.ad_key_attribute.identifier)

        if not user_id:
            continue

        is_kaavapino_user = attr.ad_key_attribute.value_type == Attribute.TYPE_USER
        value = get_in_personnel_data(user_id, attr.ad_data_key, is_kaavapino_user)

        if value:
            if attr.ad_data_key == "title":
                value = value.lower()
            set_attribute_data(attribute_data, path, value)

def _find_closest_path(target_path, path_behind, path_ahead):
    if len(target_path) == 1:
        return path_behind + target_path

    # traverse fieldset structure until a common node is found
    while len(path_behind):
        if type(path_behind[-1]) == int:
            path_ahead.append(path_behind.pop())
            continue

        current_attr = path_behind.pop()

        try:
            target_index = target_path.index(current_attr)
            target_path = target_path[target_index:]
            break
        except ValueError:
            continue

    # find a path matching the attribute we're trying to set
    while len(target_path) > 1:
        try:
            next_i = path_ahead.pop()
        except IndexError:
            next_i = 0

        path_behind += [target_path.pop(0), next_i]

    return path_behind + target_path

def set_automatic_attributes(attribute_data):
    from projects.models import AttributeAutoValue

    paths = []
    for auto_attr in AttributeAutoValue.objects.all().select_related("key_attribute", "value_attribute").prefetch_related("value_map"):
        key_attr_path = \
            get_fieldset_path(auto_attr.key_attribute) + [auto_attr.key_attribute]
        new_paths = []
        _add_paths(
            new_paths,
            [],
            key_attr_path,
            attribute_data,
        )
        for path in new_paths:
            key_path = _find_closest_path(
                key_attr_path,
                path,
                [],
            )
            paths.append((path+[auto_attr.value_attribute], key_path, auto_attr))

    for (target, source, auto_attr) in paths:
        if len(target) == 2 and len(source) == 2:
            target, source = [target[1]], [source[1]]
        key = get_attribute_data(source, attribute_data)
        if isinstance(key, list):
            value = {k: auto_attr.get_value(k) for k in key}
        else:
            value = auto_attr.get_value(key)
        if value:
            set_attribute_data(attribute_data, target, value)


def get_file_type(filename):
    return filename.split(".")[-1]


def get_attribute_lock_data(attribute_identifier):
    if "[" in attribute_identifier and "]" in attribute_identifier:
        fieldset_attribute_identifier = attribute_identifier.split("[")[0]
        fieldset_attribute_index = attribute_identifier.split("[")[1].split("]")[0]
        return {
            "fieldset_attribute_identifier": fieldset_attribute_identifier,
            "fieldset_attribute_index": fieldset_attribute_index
        }
    return {"attribute_identifier": attribute_identifier}


def get_attribute_data_filtered_response(attributes, project, use_cached=True):
    cache_key = f'attribute_data_filtered_{project.pk}'
    response = cache.get(cache_key) if use_cached else None

    if not response:
        response = {}
        attribute_data = project.attribute_data
        set_ad_data_in_attribute_data(attribute_data)
        set_geoserver_data_in_attribute_data(attribute_data)

        for key, value in attribute_data.items():
            attribute = attributes.get(key)
            if not attribute or not attribute.api_visibility:
                continue

            if not value:
                continue

            name = attribute.identifier

            if attribute.value_type == "fieldset":
                fieldset = []
                for entry in value:  # fieldset
                    fieldset_obj = {}
                    deleted = entry.get('_deleted', False)
                    if deleted:
                        continue
                    for k, v in entry.items():
                        fieldset_attr = attributes.get(k, None)
                        if not fieldset_attr or not fieldset_attr.api_visibility:
                            continue
                        if fieldset_attr.value_type == "personnel":
                            v = get_in_personnel_data(v, "name", False)
                        elif fieldset_attr.value_type in ["rich_text", "rich_text_short"]:
                            v = "".join([item["insert"] for item in v["ops"]]).strip() if v else None
                        fieldset_obj[k] = v
                    if fieldset_obj:
                        fieldset.append(fieldset_obj)
                if fieldset:
                    response[name] = fieldset
            elif attribute.value_type == "user":
                response[name] = get_in_personnel_data(value, "name", True)
            elif attribute.value_type in ["rich_text", "rich_text_short"]:
                try:
                    response[name] = "".join([item["insert"] for item in value["ops"]]).strip()
                except TypeError:
                    response[name] = value
            else:
                response[name] = value

        response = sanitize_attribute_data_filter_result(attributes, response)

        # TODO: Rename DOCUMENT_EDIT_URL_FORMAT to be generic url base
        url = settings.DOCUMENT_EDIT_URL_FORMAT.replace("<pk>", str(project.pk)).removesuffix("/edit")
        response["Projektin osoite"] = url
        response["Projekti on toistaiseksi keskeytynyt"] = project.onhold
        response["Projekti on arkistoitu"] = project.archived

        cache.set(cache_key, response, 60 * 60 * 6)

    return response


def sanitize_attribute_data_filter_result(attributes, attribute_data):
    for key, value in copy.deepcopy(attribute_data).items():
        attribute = attributes.get(key)
        if attribute is None or value is None:
            continue

        if attribute.value_type == "fieldset":
            if attribute.identifier == "hakija_fieldset":
                hakija_taho = []
                hakija_maksu_oas = []
                hakija_maksu_ehdotus = []
                hakija_maksu_hyvaksyminen = []

                for item in value:
                    if "hakija_yritys" in item.keys():
                        hakija_taho.append(f"Hakija yritys: {item.get('hakija_yritys', 'N/A')}")
                    elif "hakijan_etunimi_yksityishenkilo" in item.keys() and "hakijan_sukunimi_yksityishenkilo" in item.keys():
                        hakija_taho.append(f"Hakija yksityishenkilö")
                    if "hakijalta_perittava_maksu_oas" in item.keys():
                        hakija_maksu_oas.append(float(item.get('hakijalta_perittava_maksu_oas', 0)))
                    if "hakijalta_perittava_maksu_ehdotus" in item.keys():
                        hakija_maksu_ehdotus.append(float(item.get('hakijalta_perittava_maksu_ehdotus', 0)))
                    if "hakijalta_perittava_maksu" in item.keys():
                        hakija_maksu_hyvaksyminen.append(float(item.get('hakijalta_perittava_maksu', 0)))

                attribute_data["Hakija_taho"] = "; ".join(hakija_taho)
                attribute_data["Hakija_maksu_oas"] = sum(hakija_maksu_oas)
                attribute_data["Hakija_maksu_ehdotus"] = sum(hakija_maksu_ehdotus)
                attribute_data["Hakija_maksu_hyvaksyminen"] = sum(hakija_maksu_hyvaksyminen)
                hakija_maksu_yhteensa = sum([sum(hakija_maksu_oas), sum(hakija_maksu_ehdotus), sum(hakija_maksu_hyvaksyminen)])
                attribute_data["Kaavaprojekti_maksu_yhteensa"] = hakija_maksu_yhteensa
                attribute_data.pop("hakija_fieldset", None)
            elif attribute.identifier == "investointi_kustannukset_muu_fieldset":
                items = []
                for item in value:
                    if "investointi_kustannukset_muu_aihe" in item.keys() and "investointi_kustannukset_muu_maara" in item.keys():
                        items.append(f"{item.get('investointi_kustannukset_muu_aihe', 'N/A')}: {item.get('investointi_kustannukset_muu_maara', 'N/A')}")
                attribute_data[key] = ";".join(items)
            elif attribute.identifier == "muut_kustannukset_fieldset":
                items = []
                for item in value:
                    if "muut_kustannukset_aihe" in item.keys() and "muut_kustannukset_maara" in item.keys():
                        items.append(f"{item.get('muut_kustannukset_aihe', 'N/A')}: {item.get('muut_kustannukset_maara', 'N/A')}")
                attribute_data[key] = ";".join(items)
            elif attribute.identifier in ["tarvittava_selvitys_fieldset", "kaavoittaja_fieldset", "liikennesuunnittelun_asiantuntija_fieldset",
                              "yhteyshenkilo_maankayttosopimus_fieldset", "liikennesuunnitelma_fieldset", "paikkatietoasiantuntija_fieldset",
                              "suunnitteluavustaja_fieldset", "yleissuunnittelun_asiantuntija_fieldset", "kaupunkitilan_asiantuntija_fieldset",
                              "rakennussuojelun_asiantuntija_fieldset", "kaavoitussihteeri_fieldset", "hakemus_fieldset",
                              "paivitetty_oas_fieldset", "konsulttityo_fieldset", "yhteyshenkilo_toteuttamissopimus_fieldset",
                              "maaomaisuuden_asiantuntija_fieldset", "teknistaloudellinen_asiantuntija_fieldset"]:
                items = []
                for item in value:
                    items.append(", ".join(item for item in item.values() if item))
                attribute_data[key] = ";".join(items)
        elif attribute.value_type == "choice":
            if isinstance(value, list):
                attribute_data[key] = "; ".join(value)  # TODO value fix string
        elif attribute.value_type == "date":
            date = datetime.strptime(value, "%Y-%m-%d")
            attribute_data[key] = date.strftime("%d.%m.%Y")

    return {attributes.get(k).name if attributes.get(k) is not None else k: v for k, v in attribute_data.items()}


DOCUMENT_CONTENT_TYPES = {
    'docx': "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    'pptx': "application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"
}


TRUE = ("true", "True", "1")
