from __future__ import annotations
from typing import TYPE_CHECKING, Any, Union, Optional

if TYPE_CHECKING:
    from .models import Attribute
    from django.db.models import QuerySet

from collections import OrderedDict
import re
import requests
import json
import logging

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.exceptions import ValidationError
from requests import ReadTimeout
from rest_framework import status
from rest_framework.renderers import JSONRenderer
from rest_framework.response import Response

from users.helpers import get_graph_api_access_token
from users.serializers import PersonnelSerializer

log = logging.getLogger(__name__)


def get_fieldset_path(attr: Attribute,
                      attribute_path: list[Attribute] = [],
                      cached: bool = True,
                      orig_attr: Optional[Attribute] = None
                      ) -> list[Attribute]:
    orig_attr: Attribute = orig_attr or attr
    cache_key: str = f'projects.helpers.get_fieldset_path.{orig_attr.identifier}'
    if cached:
        cache_value: list[Attribute] = cache.get(cache_key)
        if cache_value:
            return cache_value

    if not attr.fieldsets.count():
        cache.set(cache_key, attribute_path, None)
        return attribute_path
    else:
        parent_fieldset: Attribute = attr.fieldsets.first()
        return get_fieldset_path(
            parent_fieldset,
            [parent_fieldset] + attribute_path,
            orig_attr = orig_attr,
        )


def set_attribute_data(data: Union[dict[str, list], list[dict]],
                       path: list[Union[Attribute, str]],
                       value: str) -> None:
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


def get_attribute_data(attribute_path: list[Attribute], data: dict):
    if len(attribute_path) == 0:
        return data

    if len(attribute_path) == 1:
        return data.get(attribute_path[0].identifier)

    return get_attribute_data(
        attribute_path[2:],
        data.get(attribute_path[0].identifier, [])[attribute_path[1]]
    )


def get_flat_attribute_data(data: dict[str, Any],
                            flat: dict[str, list],
                            first_run: bool = True,
                            flat_key: str = None,
                            value_types: dict = None
                            ) -> dict[str, list]:
    from projects.models import Attribute

    if first_run:
        id: str = data.get("pinonumero")
        cache_key: str = 'projects.helpers.get_flat_attribute_data'
        flats = cache.get_or_set(cache_key, OrderedDict())
        flat_key: str = str(data)
        cached_flat = flats.get((id, flat_key))

        if cached_flat:
            flats.move_to_end((id, flat_key), last=True)
            cache.set(cache_key, flats, None)
            return cached_flat

        a: Attribute
        value_types: dict[str, str] = {a.identifier: a.value_type for a in Attribute.objects.all()}

    for key, val in data.items():
        flat[key] = flat.get(key, [])
        value_type = value_types.get(key, None)

        if type(val) is list and value_type == Attribute.TYPE_FIELDSET:
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


# Updates fetched kiinteistotunnukset from Kaavoitus-API to suunnittelualueella_kiinteisto_fieldset.
# These values can't be edited or deleted in the UI and area always automatically fetched and displayed.
def update_suunnittelualueella_kiinteisto_fieldset(attribute_data):
    if not attribute_data.get("hankenumero"):
        return

    hankenumero = attribute_data["hankenumero"]

    if not attribute_data or not hankenumero or not re.compile("^\d{4}_\d{1,3}$").match(hankenumero):
        return

    url = f"{settings.KAAVOITUS_API_BASE_URL}/geoserver/v1/kiinteistotunnukset/{hankenumero}"
    if cache.get(url) is not None:
        response = cache.get(url)
    else:
        response = requests.get(
            url,
            headers={"Authorization": f"Token {settings.KAAVOITUS_API_AUTH_TOKEN}"},
            timeout=5
        )
        if response.status_code == 200:
            cache.set(url, response, 3600)  # 1 hour

    if response.status_code != 200:
        return

    if not attribute_data.get("suunnittelualueella_kiinteisto_fieldset"):
        attribute_data["suunnittelualueella_kiinteisto_fieldset"] = []

    kiinteistotunnukset = response.json()["kiinteistotunnukset"]
    for kiinteistotunnus in kiinteistotunnukset:
        attribute_data["suunnittelualueella_kiinteisto_fieldset"].append({
            "_deleted": False,
            "_automatically_added": True,
            "kiinteistoa_koskee": kiinteistotunnus
        })

def set_kaavoitus_api_data_in_attribute_data(attribute_data):
    from projects.models import Attribute

    external_data_attrs: QuerySet[Attribute] = Attribute.objects.filter(
        data_source__isnull=False,
    ).select_related("key_attribute")

    leaf_node_attrs: QuerySet[Attribute] = external_data_attrs.filter(
        data_source__isnull=False,
    ).exclude(
        value_type=Attribute.TYPE_FIELDSET,
    ).select_related("key_attribute")

    update_suunnittelualueella_kiinteisto_fieldset(attribute_data)
    flat_attribute_data = get_flat_attribute_data(attribute_data, {})

    # TODO: Timeout should be fixed in Kaavoitus-api
    """
    The reason for the timeout should be fixed in Kaavoitus-api and Kaavoitus-api should return the timeout
    response instead of generating one here manually. This works as a hotfix for now but should be fixed in future.
    """
    def get_timeout_response() -> Response:
        ret = Response(
            data='Kaavoitus-api did not return a response in time.',
            status=status.HTTP_408_REQUEST_TIMEOUT
        )
        ret.accepted_renderer = JSONRenderer()
        ret.accepted_media_type = "application/json"
        ret.renderer_context = {}
        ret.render()
        return ret

    def build_request_paths(attr: Attribute) -> dict[str, str]:
        returns: dict[str, str] = {}
        if attr.key_attribute:
            key_values = flat_attribute_data.get(
                attr.key_attribute.identifier, []
            )
        else:
            parent_attr: Attribute = Attribute.objects.get(
                identifier=attr.key_attribute_path.split(".")[0]
            )
            key_values: list[str] = flat_attribute_data.get(
                parent_attr.key_attribute.identifier, []
            )

        # Remove hyphens if the key is a kiinteistotunnus,
        # geoserver does not support the hyphened form
        for value in key_values:
            if attr.data_source in [
                Attribute.SOURCE_FACTA, Attribute.SOURCE_GEOSERVER
            ]:
                pk: str = "".join(str(value).split("-"))
            else:
                pk: str = str(value)

            path: str = attr.data_source.replace("<pk>", pk)
            returns[value] = f"{settings.KAAVOITUS_API_BASE_URL}{path}"

        return returns

    fetched_data: dict[Attribute, dict[str, str]] = {
        attr: build_request_paths(attr)
        for attr in external_data_attrs.exclude(
            data_source=Attribute.SOURCE_PARENT_FIELDSET,
        ) if attr is not None
    }

    for attr, urls in fetched_data.items():
        for key, value in urls.items():
            url: str = value
            if cache.get(url) is not None:
                response = cache.get(url)
            else:
                try:
                    response = requests.get(
                        url,
                        headers={"Authorization": f"Token {settings.KAAVOITUS_API_AUTH_TOKEN}"},
                        timeout=180
                    )
                except ReadTimeout:
                    log.error("Request timed out for url: {}".format(url))
                    response = get_timeout_response()

                if response.status_code in [200, 400, 404, 408]:
                    cache.set(url, response, 86400)  # 24 hours
                else:
                    cache.set(url, response, 900)  # 15 minutes

            if response.status_code == 200:
                fetched_data[attr][key] = response.json()
            else:
                fetched_data[attr][key] = None

    def get_deep(source: dict, keys: Union[str, list], default: dict = None) -> dict:
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

    def get_in_attribute_data(attribute_path: list[Attribute], data: Union[dict, list]) -> list:
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

    def get_branch_paths(data: dict[Attribute, dict[str, str]],
                         solved_path,
                         remaining_path: list[Attribute],
                         saved_keys: dict = None,
                         first_run: bool = True
                         ):
        if saved_keys is None:
            saved_keys = {}
        if first_run:
            saved_keys = {}

        if not remaining_path:
            leaf_paths.append([solved_path] if first_run else solved_path)
            return

        data_source_key: Optional[str] = None
        data_source_keys: Optional[list] = None
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
        fieldset_path: list[Attribute] = get_fieldset_path(attr) + [attr]

        get_branch_paths(
            fetched_data,
            [],
            fieldset_path,
        )

    def get_in_fetched_data(data, attribute_path: list):
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

    def set_in_attribute_data(data: Union[dict, list], path: list[Union[Attribute, tuple[int]]], value: str) -> None:
        try:
            next_key: str = path[0].identifier
        except AttributeError:
            next_key: int = path[0][0]

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


def get_ad_user(id: str) -> Union[None, Response, str]:
    url = f"{settings.GRAPH_API_BASE_URL}/v1.0/users/{id}?$select=companyName,givenName,id,jobTitle,mail,mobilePhone,businessPhones,officeLocation,surname"
    try:
        response = cache.get(url)
    except TypeError:
        return None

    if not response:
        if response is not None:
            return None

        token: str = get_graph_api_access_token()
        if not token:
            return Response(
                "Cannot get access token",
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
        response = requests.get(
            url, headers={"Authorization": f"Bearer {token}"}
        )

        cache.set(url, response, 3600)

        if not response:
            return None

    return response.json()


def _add_paths(paths: list, solved_path: list, remaining_path: list, parent_data: dict) -> None:
    from projects.models import Attribute

    if remaining_path[0].value_type != Attribute.TYPE_FIELDSET:
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


def get_in_personnel_data(id: str, key: str, is_kaavapino_user: bool) -> Any:
    User = get_user_model()

    if is_kaavapino_user:
        try:
            id: str = id.uuid
        except AttributeError:
            pass

        try:
            id: str = User.objects.get(uuid=id).ad_id
        except (User.DoesNotExist, ValidationError):
            return None

    user: str = get_ad_user(id)
    return PersonnelSerializer(user).data.get(key)


def set_ad_data_in_attribute_data(attribute_data: dict[str, Any]) -> None:
    from projects.models import Attribute
    paths: list = []

    attributes: QuerySet[Attribute] = Attribute.objects.filter(
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

        is_kaavapino_user: bool = attr.ad_key_attribute.value_type == Attribute.TYPE_USER
        value = get_in_personnel_data(user_id, attr.ad_data_key, is_kaavapino_user)

        if value:
            set_attribute_data(attribute_data, path, value)


def _find_closest_path(target_path: list, path_behind: list, path_ahead: list) -> list:
    if len(target_path) == 1:
        return path_behind + target_path

    # traverse fieldset structure until a common node is found
    while len(path_behind):
        if type(path_behind[-1]) == int:
            path_ahead.append(path_behind.pop())
            continue

        current_attr = path_behind.pop()

        try:
            target_index: int = target_path.index(current_attr)
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


def set_automatic_attributes(attribute_data: dict[str, Any]) -> None:
    from projects.models import AttributeAutoValue

    paths: list = []
    auto_attr: AttributeAutoValue
    for auto_attr in AttributeAutoValue.objects.all().select_related("key_attribute", "value_attribute").prefetch_related("value_map"):
        key_attr_path = \
            get_fieldset_path(auto_attr.key_attribute) + [auto_attr.key_attribute]
        new_paths: list = []
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
        value = auto_attr.get_value(key)
        if value:
            set_attribute_data(attribute_data, target, value)


def get_file_type(filename: str) -> str:
    return filename.split(".")[-1]


DOCUMENT_CONTENT_TYPES = {
    'docx': "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    'pptx': "application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"
}


TRUE = ("true", "True", "1")
