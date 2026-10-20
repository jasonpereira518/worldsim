"""Natural Earth admin-0 (1:50m) countries and admin-1 (1:10m) states/provinces, pinned to a release tag."""
from __future__ import annotations

import json
import re

from . import need, prov

TAG = 'v5.1.2'
AS_OF = '2022-05-13'  # v5.1.2 release date
BASE = f'https://raw.githubusercontent.com/nvkelso/natural-earth-vector/{TAG}/geojson/'

ADMIN0 = {
    'id': 'ne_admin0_50m',
    'name': 'Natural Earth admin-0 countries, 1:50m',
    'source': f'Natural Earth {TAG}',
    'url': BASE + 'ne_50m_admin_0_countries.geojson',
    'license': 'Public domain',
    'confidence': 'high',
    'fields': ['iso3', 'iso2', 'name', 'name_long', 'formal_name', 'ne_type', 'sovereign_iso3', 'continent', 'subregion',
               'centroid (area-weighted)', 'label point', 'geometry'],
    'used_for': 'Country keys, names, sovereignty type, boundaries and centroids',
    'max_age_days': 1095,
    'note': 'De facto boundaries as drawn by Natural Earth. Features without an ISO 3166-1 code (Somaliland, N. Cyprus, '
            'Siachen Glacier, Australian minor dependencies) are excluded; Kosovo is keyed XKX as in the World Bank.',
}
ADMIN1 = {
    'id': 'ne_admin1_10m',
    'name': 'Natural Earth admin-1 states and provinces, 1:10m',
    'source': f'Natural Earth {TAG}',
    'url': BASE + 'ne_10m_admin_1_states_provinces.geojson',
    'license': 'Public domain',
    'confidence': 'medium',
    'fields': ['id (ne_id)', 'iso3', 'name', 'type', 'iso_3166_2', 'lat/lon (label point)', 'geometry'],
    'used_for': 'First regional level below countries (persona placement, regional aggregation)',
    'max_age_days': 1095,
    'note': '1:10m because the 1:50m admin-1 layer covers only a few countries. Names and divisions can lag recent reforms.',
}


def iso3_of(p: dict) -> str | None:
    """NE marks some ISO codes -99 (France, Norway, Kosovo). ISO_A3_EH fixes those, but also maps
    minor dependencies onto their sovereign (Ashmore → AUS), so only trust it when it equals ADM0_A3."""
    if p['ISO_A3'] != '-99':
        return p['ISO_A3']
    if p['ISO_A3_EH'] != '-99' and p['ISO_A3_EH'] == p['ADM0_A3']:
        return p['ISO_A3_EH']
    return {'KOS': 'XKX'}.get(p['ADM0_A3'])


def centroid(geom: dict) -> tuple[float, float]:
    """Area-weighted (lat, lon) of a Polygon/MultiPolygon in planar lon/lat. Shapes split at the
    antimeridian (Russia, Fiji, USA) are unwrapped to 0..360 first so the parts average correctly."""
    polys = geom['coordinates'] if geom['type'] == 'MultiPolygon' else [geom['coordinates']]
    xs = [x for poly in polys for ring in poly for x, _ in ring]
    shift = max(xs) - min(xs) > 180
    A = cx = cy = 0.0
    for poly in polys:
        for i, ring in enumerate(poly):
            pts = [((x + 360 if shift and x < 0 else x), y) for x, y in ring]
            a = sx = sy = 0.0
            for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
                c = x0 * y1 - x1 * y0
                a, sx, sy = a + c, sx + (x0 + x1) * c, sy + (y0 + y1) * c
            k = (1 if i == 0 else -1) * (1 if a >= 0 else -1)  # shells add, holes subtract, whatever the winding
            A, cx, cy = A + k * a, cx + k * sx, cy + k * sy
    lon = cx / (3 * A)
    return round(cy / (3 * A), 4), round(lon - 360 if lon > 180 else lon, 4)


def _keep(props: list[str]):
    """Cache only the properties we read (the admin-1 file is 40 MB raw)."""
    return lambda gj: {'features': [{'properties': {k: f['properties'].get(k) for k in props}, 'geometry': f['geometry']}
                                    for f in gj['features']]}


def run_admin0(fetch, ctx: dict) -> dict:
    gj = fetch.json(ADMIN0['url'], transform=_keep(
        ['ISO_A3', 'ISO_A3_EH', 'ADM0_A3', 'ISO_A2', 'ISO_A2_EH', 'NAME', 'NAME_LONG', 'FORMAL_EN', 'TYPE', 'ADMIN',
         'SOVEREIGNT', 'CONTINENT', 'SUBREGION', 'LABEL_X', 'LABEL_Y']))
    p = prov(ADMIN0, AS_OF, fetch.retrieved)
    feats = [(iso3_of(f['properties']), f) for f in gj['features']]
    by_admin = {f['properties']['ADMIN']: iso3 for iso3, f in feats if iso3}
    rows, adm0 = [], {}
    for iso3, f in feats:
        a = f['properties']
        if not iso3 or iso3 in adm0.values():
            continue
        adm0[a['ADM0_A3']] = iso3
        # ISO_A2_EH first: ISO_A2 is -99 for France/Norway/Kosovo and 'CN-TW' for Taiwan
        iso2 = next((v for v in (a['ISO_A2_EH'], a['ISO_A2']) if v and re.fullmatch('[A-Z]{2}', v)), None)
        lat, lon = centroid(f['geometry'])
        rows.append({
            'iso3': iso3, 'iso2': iso2, 'name': a['NAME'], 'name_long': a['NAME_LONG'], 'formal_name': a['FORMAL_EN'],
            'ne_type': a['TYPE'], 'sovereign_iso3': by_admin.get(a['SOVEREIGNT']), 'continent': a['CONTINENT'],
            'subregion': a['SUBREGION'], 'centroid_lat': lat, 'centroid_lon': lon, 'label_lat': a['LABEL_Y'],
            'label_lon': a['LABEL_X'], 'geometry': json.dumps(f['geometry'], separators=(',', ':')), **p,
        })
    iso2_to_iso3 = {r['iso2']: r['iso3'] for r in rows if r['iso2']}
    return {'tables': {'countries': rows}, 'as_of': AS_OF, 'ctx': {'adm0_to_iso3': adm0, 'iso2_to_iso3': iso2_to_iso3}}


def run_admin1(fetch, ctx: dict) -> dict:
    gj = fetch.json(ADMIN1['url'], transform=_keep(['ne_id', 'adm0_a3', 'name', 'name_en', 'type_en', 'iso_3166_2', 'latitude', 'longitude']))
    adm0 = need(ctx, 'adm0_to_iso3', ADMIN0['id'])
    p = prov(ADMIN1, AS_OF, fetch.retrieved)
    rows = [
        {'id': a['ne_id'], 'iso3': adm0[a['adm0_a3']], 'name': a['name_en'] or a['name'], 'type': a['type_en'],
         'iso_3166_2': a['iso_3166_2'], 'lat': a['latitude'], 'lon': a['longitude'],
         'geometry': json.dumps(f['geometry'], separators=(',', ':')), **p}
        for f in gj['features'] for a in [f['properties']]
        if a['adm0_a3'] in adm0 and f['geometry'] and (a['name_en'] or a['name'])
    ]
    return {'tables': {'admin1': rows}, 'as_of': AS_OF}
