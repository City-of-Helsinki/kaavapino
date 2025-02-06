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

def get_dl_vis_bool_name(group_name):
    vis_bool_map = {
        'kaynnistys_1': None,
        'periaatteet_esillaolokerta_1': 'jarjestetaan_periaatteet_esillaolo_1',
        'periaatteet_esillaolokerta_2': 'jarjestetaan_periaatteet_esillaolo_2',
        'periaatteet_esillaolokerta_3': 'jarjestetaan_periaatteet_esillaolo_3',
        'periaatteet_lautakuntakerta_1': 'periaatteet_lautakuntaan_1',
        'periaatteet_lautakuntakerta_2': 'periaatteet_lautakuntaan_2',
        'periaatteet_lautakuntakerta_3': 'periaatteet_lautakuntaan_3',
        'periaatteet_lautakuntakerta_4': 'periaatteet_lautakuntaan_4',
        'oas_esillaolokerta_1': 'jarjestetaan_oas_esillaolo_1',
        'oas_esillaolokerta_2': 'jarjestetaan_oas_esillaolo_2',
        'oas_esillaolokerta_3': 'jarjestetaan_oas_esillaolo_3',
        'luonnos_esillaolokerta_1': 'jarjestetaan_luonnos_esillaolo_1',
        'luonnos_esillaolokerta_2': 'jarjestetaan_luonnos_esillaolo_2',
        'luonnos_esillaolokerta_3': 'jarjestetaan_luonnos_esillaolo_3',
        'luonnos_lautakuntakerta_1': 'kaavaluonnos_lautakuntaan_1',
        'luonnos_lautakuntakerta_2': 'kaavaluonnos_lautakuntaan_2',
        'luonnos_lautakuntakerta_3': 'kaavaluonnos_lautakuntaan_3',
        'luonnos_lautakuntakerta_4': 'kaavaluonnos_lautakuntaan_4',
        'ehdotus_nahtavillaolokerta_1': 'kaavaehdotus_nahtaville_1',
        'ehdotus_nahtavillaolokerta_2': 'kaavaehdotus_uudelleen_nahtaville_2',
        'ehdotus_nahtavillaolokerta_3': 'kaavaehdotus_uudelleen_nahtaville_3',
        'ehdotus_nahtavillaolokerta_4': 'kaavaehdotus_uudelleen_nahtaville_4',
        'ehdotus_lautakuntakerta_1': 'kaavaehdotus_lautakuntaan_1',
        'ehdotus_lautakuntakerta_2': 'kaavaehdotus_lautakuntaan_2',
        'ehdotus_lautakuntakerta_3': 'kaavaehdotus_lautakuntaan_3',
        'ehdotus_lautakuntakerta_4': 'kaavaehdotus_lautakuntaan_4',
        'tarkistettu_ehdotus_lautakuntakerta_1': 'tarkistettu_ehdotus_lautakuntaan_1',
        'tarkistettu_ehdotus_lautakuntakerta_2': 'tarkistettu_ehdotus_lautakuntaan_2',
        'tarkistettu_ehdotus_lautakuntakerta_3': 'tarkistettu_ehdotus_lautakuntaan_3',
        'tarkistettu_ehdotus_lautakuntakerta_4': 'tarkistettu_ehdotus_lautakuntaan_4',
        'hyvaksyminen_1': None,
        'voimaantulo_1': None
    }
    return vis_bool_map[group_name] if group_name in vis_bool_map else None

def should_display_deadline(project, deadline):
    if not project or not deadline:
        # No reason to exclude
        return True
    vis_bool = get_dl_vis_bool_name(deadline.deadlinegroup)
    if deadline.subtype != project.subtype:
        return False
    elif deadline.phase.name == "Periaatteet" and not project.create_principles:
        return False
    elif deadline.phase.name == "Luonnos" and not project.create_draft:
        return False
    elif vis_bool and not project.attribute_data.get(vis_bool):
        return False
    return True