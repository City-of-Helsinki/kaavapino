# -*- coding: UTF-8 -*-
import csv
import json
import os
import re
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from random import randint

import django
from django.contrib.gis.gdal import CoordTransform, SpatialReference
from django.contrib.gis.geos import GEOSGeometry, MultiPolygon
from django.core.serializers.json import DjangoJSONEncoder

from projects.models import Attribute, AttributeValueChoice, Project, ProjectPhase, ProjectPhaseLog, ProjectType
from projects.models.utils import create_identifier
from users.models import User

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "kaavapino.settings")
django.setup()


# read the ksv planning metadata
f = open('data/ksv_kaavahanke-meta.csv', 'r', encoding='utf-8')
# skip blank header line
next(f)
# initialize the reader
reader = csv.DictReader(f, delimiter='|')
# strip the whitespace
reader = ({str(k).strip(): str(v).strip() for k, v in row.items()} for row in reader)

projects = {}

attr_values = {}

for row in reader:
    pr_id = row.get('PROJECT_TUNNISTENUMERO')
    # omit Oracle separator lines
    if set(pr_id) <= set('-'):
        continue

    if not pr_id:
        print('Planning project id empty, omitting project')
        continue
    # omit projects without identifiers
    if not pr_id:
        print('Omitting planning project without id')
        continue

    for key, val in row.items():
        attr_values.setdefault(key, []).append(val)

    # check duplicate identifiers
    try:
        assert pr_id not in projects
    except AssertionError:
        raise AssertionError(pr_id + ' is duplicate id')
    projects[pr_id] = row
    # print('Metadata for planning project id ' + pr_id + ' found')


# read the ksv planning metadata
f = open('data/ksv_kaavahanke-meta.csv', 'r', encoding='utf-8')
# skip blank header line
next(f)
# initialize the reader
reader = csv.reader(f, delimiter='|')
# strip the whitespace
# reader = ({str(k).strip(): str(v).strip() for k, v in row.items()} for row in reader)


date_column_map = {
    10: 'oas_aineiston_esillaoloaika_alkaa',
    11: 'oas_aineiston_esillaoloaika_paattyy',
    26: 'ehdotuksen_suunniteltu_lautakuntapaivamaara_arvio',
    16: 'ehdotuksen_esittely_lautakunnalle_pvm_toteutunut',
    27: 'ehdotuksesta_paatetty_lautakunnassa_pvm_toteutunut',
    # 19: 'tarkistetusta ehdotuksesta päätetty lautakunnassa, pvm (toteutunut)',
    # 46: 'hyväksytty kaupunginvaltuustossa',
    # 21: 'lainvoimainen',
}

date_values = defaultdict(dict)
phase_names = ['Käynnistys', 'OAS', 'Ehdotus', 'Tarkistettu ehdotus', 'Kanslia-Khs-Valtuusto', 'Voimaantulo']
phases = {}
for phase_name in phase_names:
    phases[phase_name] = ProjectPhase.objects.get(name=phase_name)
phase_user = User.objects.first()

for row in reader:
    row = [str(v).strip() for v in row]
    if not row or row[0] == '-------------':
        continue

    try:
        pr_id = row[38]
    except IndexError:
        continue

    if not pr_id or pr_id == 'PROJECT_TUNNISTENUMERO' or set(pr_id) <= set('-'):
        continue

    for column_num, attribute_name in date_column_map.items():
        if not row[column_num]:
            continue

        date_values[pr_id][attribute_name] = datetime.strptime(row[column_num], "%d.%m.%Y").date()

    if row[10]:
        try:
            k_date = datetime.strptime(row[10], "%d.%m.%Y").date()
            date_values[pr_id]['Käynnistys'] = k_date - timedelta(days=randint(30*3, 30*5))
            date_values[pr_id]['OAS'] = k_date - timedelta(days=30*2)
        except ValueError:
            pass

    if 'Käynnistys' not in date_values[pr_id]:
        matches = re.match(r'\w+\s*(\d{4})-\d+', row[6])  # Diaarinumero
        if matches:
            date_values[pr_id]['Käynnistys'] = date(day=1, month=1, year=int(matches.group(1)))

    if row[11]:
        try:
            l_date = datetime.strptime(row[11], "%d.%m.%Y").date()
            date_values[pr_id]['Ehdotus'] = l_date
        except ValueError:
            pass

    if row[18]:
        try:
            s_date = datetime.strptime(row[18], "%d.%m.%Y").date()
            date_values[pr_id]['Tarkistettu ehdotus'] = s_date
        except ValueError:
            pass

    if row[19]:
        try:
            t_date = datetime.strptime(row[19], "%d.%m.%Y").date()
            date_values[pr_id]['Kanslia-Khs-Valtuusto'] = t_date
        except ValueError:
            pass

    if row[21]:
        try:
            v_date = datetime.strptime(row[21], "%d.%m.%Y").date()
            date_values[pr_id]['Voimaantulo'] = v_date
        except ValueError:
            pass

for key, values in attr_values.items():
    print(key)
    counter = Counter(values)
    if len(counter.keys()) > 100:
        continue
    for name, count in counter.items():
        print("\t%-5d %s" % (count, name))

# save the ksv planning metadata with geometry
f = open('data/ksv_kaavahanke.json', 'r', encoding='utf-8')
json_dict = json.load(f)
for feat in json_dict['features']:
    props = feat['properties']
    pr_id = props.get('TUNNISTENUMERO', '')
    if not pr_id:
        print('Planning project id empty, omitting project')
        continue
    try:
        geom = feat['geometry']
        coord = geom['coordinates']
    except KeyError:
        print('Geometry for planning project id ' + pr_id + ' missing, omitting project')
        continue
    if not coord:
        print('Geometry for planning project id ' + pr_id + ' null, omitting project')
        continue
    # print('Geometry for planning project id ' + pr_id + ' found')
    if pr_id not in projects:
        continue
    project = projects[pr_id]
    project['geometry'] = geom


f = open('data/Kerrosalainventaari_data_08_2017.csv', 'r', encoding='utf-8')
# initialize the reader
reader = csv.DictReader(f)


KERROS_ATTRS = ('Asuminen_yht', 'KERROSTALO_K', 'KERROSTALO_V', 'KERROSTALO_M', 'PIENTALO_K', 'PIENTALO_V', 'PIENTALO_M')
for row in reader:
    pr_id = row['Hankenumero']
    if pr_id not in projects:
        continue
    project = projects[pr_id]
    for attr in KERROS_ATTRS:
        project['PROJECT_%s' % attr.upper()] = row[attr]


ATTRIBUTE_MAP = {
    'kaavahankkeen_nimi': 'kaavahankkeen_nimi',
    'kaavahanke_kuvaus': 'suunnittelualueen_kuvaus',
    'vastuuhenkilo': 'kaavan_valmistelijan_nimi',
    'vastuuyksikko': None,
    'muut_vastuuhenkilot': None,
    'diaarinumero': 'diaarinumero',
    'kaavanumero': None,
    'hanketyyppi': None,
    'vireillaolo': None,
    'oa': 'oas_aineiston_esillaoloaika_alkaa',
    # 'su': None,
    # 'lu': None,
    # 'eh': None,
    'la': None,
    # 'kv': None,
    'ehdotus_kslk_suu': None,
    # 'hanke_tila'
    'toimsuunnitelma_hanke': None,
    'tunnistenumero': None,
    'suojelukaava': None,
    'hyvaksyja': 'kaavan_hyvaksyjataho',
    'hy': None,
    'lisatietoja': None,
    'ka': None,
    'kaavaarkistotilassa': None,
    'esittelysuun_selite_eh': None,
    'esittelysuun_selite_la': None,
    'esittelysuun_selite_lu': None,
    'esittelysuun_selite_su': None,
    'uutta_tai_siirrettv_in': 'uutta_tai_siirettavaa_infraa',
    #: 'oas_aineiston_esillaoloaika_paattyy',
    #: 'ehdotuksen_suunniteltu_lautakuntapaivamaara_arvio',
    #: 'ehdotuksen_esittely_lautakunnalle_pvm_toteutunut',
    'la': 'ehdotuksesta_paatetty_lautakunnassa_pvm_toteutunut',

    'kerrostalo_k': 'asuminen_kerrostalo_uusi_k_m2kunta',
    'kerrostalo_v': 'asuminen_kerrostalo_uusi_k_m2valtio',
    'kerrostalo_m': 'asuminen_kerrostalo_uusi_k_m2muut',
    'kerrostalo_k': 'asuminen_pientalo_uusi_k_m2kunta',
    'kerrostalo_v': 'asuminen_pientalo_uusi_k_m2valtio',
    'kerrostalo_m': 'asuminen_pientalo_uusi_k_m2muut',
    'asuminen_yht': 'asuminen_yhteensa',

}

PHASE_MAP = {
    '01 Suunnitteluvaihe': 'OAS',
    '02 Vireilletullut': 'Ehdotus',
    '03 Suunnitteluperiaatteet': 'OAS',
    '04 Kaavaluonnos': 'Ehdotus',
    '05 Kaavaehdotus': 'Tarkistettu ehdotus',
    '06 Tarkistettu kaavaehdotus': 'Kanslia-Khs-Valtuusto',
    '07 Hyväksytty': 'Tarkistettu ehdotus',
    '08 Lainvoimainen': 'Voimaantulo',
    '13 Rauennut': None
}

strategy_choices = set(
    attr_values['PROJECT_TAVOITE'] + attr_values['PROJECT_TAVOITE_2'] + attr_values['PROJECT_TAVOITE_3']
)

attr_obj = Attribute.objects.get(identifier='strategiakytkenta')
attr_obj.multiple_choice = True
attr_obj.save()

AttributeValueChoice.objects.filter(attribute=attr_obj).delete() # FIXME
strategy_choices = sorted([x for x in strategy_choices if x and x != 'None'], key=lambda x: (int(x.split('.')[0]), int(x.split('.')[1].split(' ')[0])))
strategy_choice_objs = {}
for idx, c in enumerate(strategy_choices):
    obj = AttributeValueChoice(identifier=create_identifier(c), value=c, index=idx, attribute=attr_obj)
    obj.save()
    strategy_choice_objs[c] = obj

project_dict = {x.identifier: x for x in Project.objects.all()}
attribute_dict = {x.identifier: x for x in Attribute.objects.all()}
project_type, _ = ProjectType.objects.get_or_create(name='asemakaava')

ct = CoordTransform(SpatialReference(3879), SpatialReference('WGS84'))

for project in projects.values():
    pr_id = project['PROJECT_TUNNISTENUMERO']
    assert pr_id
    if project['PROJECT_HANKETYYPPI'] != 'asemakaava':
        continue

    obj = project_dict.get(pr_id)
    if not obj:
        obj = Project(identifier=pr_id)
    obj.type = project_type
    obj.name = project['PROJECT_KAAVAHANKKEEN_NIMI']

    phase = PHASE_MAP.get(project['PROJECT_KAAVAVAIHE'], None)
    if phase:
        obj.phase = ProjectPhase.objects.get(name=phase)
    else:
        obj.phase = None

    print(obj.name)
    print('\tdiaarinumero: %s' % project['PROJECT_DIAARINUMERO'])
    print('\tvaihe: %s' % project['PROJECT_KAAVAVAIHE'])
    for attr in ATTRIBUTE_MAP.keys():
        if len(attr) != 2:
            continue
        val = project.get('PROJECT_%s' % (attr.upper()))
        if val != '' and val is not None:
            print("\t%s: %s" % (attr, val))

    data = obj.attribute_data
    for pr_attr, obj_attr in ATTRIBUTE_MAP.items():
        val = project.get('PROJECT_%s' % (pr_attr.upper()))
        if val != '' and val is not None:
            if not obj_attr:
                # print("%s: %s" % (pr_attr, val))
                continue
            if pr_attr in ('oa', 'la'):
                val = datetime.strptime(val, '%d.%m.%Y').strftime('%Y-%m-%d')
            data[obj_attr] = val

    strategy = project.get('PROJECT_TAVOITE'), project.get('PROJECT_TAVOITE_2'), project.get('PROJECT_TAVOITE_3')
    strategy = [strategy_choice_objs[x].identifier for x in strategy if x]
    data['strategiakytkenta'] = strategy
    if 'null' in data:
        del data['null']

    # Save date fields
    if pr_id in date_values:
        for attribute_name in date_column_map.values():
            if attribute_name in date_values[pr_id]:
                data[attribute_name] = date_values[pr_id][attribute_name]

    geometry = project.get('geometry')
    if geometry is not None:
        # Drop the Z dimension
        coords = geometry['coordinates']
        if geometry['type'] == 'Polygon':
            geometry['coordinates'] = [[[y[0], y[1]] for y in x] for x in coords]
            geometry = MultiPolygon(GEOSGeometry(json.dumps(geometry)))
        elif geometry['type'] == 'MultiPolygon':
            geometry['coordinates'] = [[[[z[0], z[1]] for z in y] for y in x] for x in coords]
            geometry = GEOSGeometry(json.dumps(geometry))
        geometry.transform(ct)

    obj.geometry = geometry

    obj.save()

    # Save ProjectPhaseLogs
    if pr_id in date_values:
        for phase_name in phase_names:
            if phase_name not in date_values[pr_id]:
                continue

            log_entry = None
            try:
                log_entry = ProjectPhaseLog.objects.get(project=obj, phase=phases[phase_name])
            except ProjectPhaseLog.DoesNotExist:
                log_entry = ProjectPhaseLog(project=obj, phase=phases[phase_name])

            log_entry.user = phase_user
            # TODO: remove auto_now_add because this doesn't have any effect if the log entry is new
            log_entry.created_at = date_values[pr_id][phase_name]
            log_entry.save()
