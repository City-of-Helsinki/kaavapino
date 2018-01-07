# -*- coding: UTF-8 -*-
import json
import csv
from datetime import datetime

import os
import django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "kaavapino.settings")
django.setup()

from django.contrib.gis.geos import GEOSGeometry, MultiPolygon
from django.contrib.gis.gdal import CoordTransform, SpatialReference
from projects.models import Project, ProjectType, ProjectPhase, Attribute, AttributeValueChoice
from projects.models.utils import create_identifier


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


from collections import Counter

for key, values in attr_values.items():
    print(key)
    counter = Counter(values)
    if len(counter.keys()) > 100:
        continue
    for name, count in counter.items():
        print("\t%-5d %s" % (count, name))


# save the ksv planning metadata with geometry
f = open('data/ksv_kaavahanke.json', 'r')
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


ATTRIBUTE_MAP = {
    'kaavahankkeen_nimi': 'kaavahankkeen_nimi',
    'kaavahanke_kuvaus': None,
    'vastuuhenkilo': 'kaavan_valmistelijan_nimi',
    'vastuuyksikko': None,
    'muut_vastuuhenkilot': None,
    'diaarinumero': 'diaarinumero',
    'kaavanumero': None,
    'hanketyyppi': None,
    'vireillaolo': None,
    'oa': None,
    'su': None,
    'lu': None,
    'eh': None,
    'la': None,
    'kv': None,
}

PHASE_MAP = {
    '01 Suunnitteluvaihe': 'Käynnistys',
    '02 Vireilletullut': 'Käynnistys',
    '03 Suunnitteluperiaatteet': 'Suunnitteluperiaatteet',
    '04 Kaavaluonnos': 'Luonnos',
    '05 Kaavaehdotus': 'Ehdotus',
    '06 Tarkistettu kaavaehdotus': 'Tarkistettu ehdotus',
    '07 Hyväksytty': 'Kanslia-Khs-Valtuusto',
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

    data = obj.attribute_data
    for pr_attr, obj_attr in ATTRIBUTE_MAP.items():
        val = project.get('PROJECT_%s' % (pr_attr.upper()))
        if val != '' and val is not None:
            if not obj_attr:
                # print("%s: %s" % (pr_attr, val))
                continue
            data[obj_attr] = val

    strategy = project.get('PROJECT_TAVOITE'), project.get('PROJECT_TAVOITE_2'), project.get('PROJECT_TAVOITE_3')
    strategy = [strategy_choice_objs[x].identifier for x in strategy if x]
    data['strategiakytkenta'] = strategy
    if 'null' in data:
        del data['null']

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
    print("saved %s" % obj.id)
