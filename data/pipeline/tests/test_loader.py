"""Loader and pure-logic tests. No network: synthetic rows into a temporary snapshot root."""
import json

import duckdb
import pytest

from pipeline.jobs.companies import pick, slug
from pipeline.jobs.naturalearth import centroid, iso3_of
from pipeline.store import build_snapshot, latest, parquet

P = {'source': 'test', 'as_of': '2026-10-08', 'confidence': 'high', 'license': 'CC BY 4.0', 'retrieved': '2026-10-20T12:00:00Z'}
SQUARE = {'type': 'Polygon', 'coordinates': [[[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]]]}


def country(**kw):
    return {'iso3': 'VNM', 'iso2': 'VN', 'name': 'Vietnam', 'name_long': None, 'formal_name': None, 'ne_type': 'Sovereign country',
            'sovereign_iso3': 'VNM', 'continent': 'Asia', 'subregion': None, 'centroid_lat': 16.0, 'centroid_lon': 106.0,
            'label_lat': None, 'label_lon': None, 'geometry': json.dumps(SQUARE), **P, **kw}


def indicator(**kw):
    return {'iso3': 'VNM', 'indicator': 'SP.POP.TOTL', 'key': 'population', 'name': 'Population, total', 'unit': 'people',
            'year': 2025, 'value': 101598527.0, **P, **kw}


def test_loader_round_trips_rows_with_provenance(tmp_path):
    snap = build_snapshot('t1', {'countries': [country()], 'indicators': [indicator()]}, {'job': {'status': 'live'}}, root=tmp_path)
    assert latest(tmp_path) == snap
    assert json.loads((snap / 'manifest.json').read_text())['tables']['indicators'] == 1
    row = duckdb.sql(f"SELECT iso3, value, source, CAST(as_of AS VARCHAR), license, retrieved FROM read_parquet('{parquet(snap, 'indicators')}')").fetchone()
    assert row[:5] == ('VNM', 101598527.0, 'test', '2026-10-08', 'CC BY 4.0')
    assert str(row[5]) == '2026-10-20 12:00:00'
    assert (snap / 'company_financials.parquet').exists()  # every schema table is published, even when empty


@pytest.mark.parametrize('bad', [
    country(iso3='vn'),            # ISO3 must be three upper-case letters
    country(license=None),         # provenance is mandatory
    country(confidence='certain'),
    country(centroid_lat=95),
])
def test_loader_rejects_contract_violations(tmp_path, bad):
    with pytest.raises(ValueError, match='countries'):
        build_snapshot('bad', {'countries': [bad]}, {}, root=tmp_path)
    assert latest(tmp_path) is None  # nothing published


def test_financial_rows_need_a_value_or_a_reason(tmp_path):
    row = {'company_id': 'x', 'metric': 'revenue', 'value': None, 'unit': None, 'period_start': None, 'period_end': None,
           'form': None, 'concept': None, 'missing_reason': None, **P}
    with pytest.raises(ValueError):
        build_snapshot('bad', {'company_financials': [row]}, {}, root=tmp_path)
    build_snapshot('ok', {'company_financials': [{**row, 'missing_reason': 'not an SEC filer'}]}, {}, root=tmp_path)


def test_centroid():
    assert centroid(SQUARE) == (1.0, 1.0)
    holed = {'type': 'Polygon', 'coordinates': [SQUARE['coordinates'][0], [[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]}
    assert centroid(holed) == (round(7 / 6, 4), round(7 / 6, 4))  # hole in the lower-left quarter pulls it up-right
    fiji = {'type': 'MultiPolygon', 'coordinates': [[[[178, -18], [180, -18], [180, -16], [178, -16], [178, -18]]],
                                                    [[[-180, -18], [-178, -18], [-178, -16], [-180, -16], [-180, -18]]]]}
    lat, lon = centroid(fiji)
    assert lat == -17.0 and abs(abs(lon) - 180) < 1e-6  # on the antimeridian, not at 0°


def test_iso3_fixes():
    assert iso3_of({'ISO_A3': '-99', 'ISO_A3_EH': 'FRA', 'ADM0_A3': 'FRA'}) == 'FRA'
    assert iso3_of({'ISO_A3': '-99', 'ISO_A3_EH': '-99', 'ADM0_A3': 'KOS'}) == 'XKX'
    assert iso3_of({'ISO_A3': '-99', 'ISO_A3_EH': 'AUS', 'ADM0_A3': 'ATC'}) is None  # Ashmore is not Australia
    assert iso3_of({'ISO_A3': '-99', 'ISO_A3_EH': '-99', 'ADM0_A3': 'SOL'}) is None


def test_slug():
    assert slug('Apple Inc.') == 'apple'
    assert slug('Volkswagen Group') == 'volkswagen'
    assert slug('Toyota Motor Corporation') == 'toyota-motor'
    assert slug('Nestlé S.A.') == 'nestle'


def test_edgar_pick_latest_annual_in_reporting_currency():
    def fy(start, end, val, form='10-K'):
        return {'start': start, 'end': end, 'val': val, 'form': form, 'filed': '2025-01-01'}
    facts = {'us-gaap': {'Revenues': {'units': {
        'USD': [fy('2023-01-01', '2023-12-31', 1), fy('2024-01-01', '2024-12-31', 2), fy('2024-10-01', '2024-12-31', 99),
                fy('2025-01-01', '2025-12-31', 3, '10-Q')],
        'EUR': [fy('2024-01-01', '2024-12-31', 7)],
    }}}}
    v = pick(facts, 'duration', [('us-gaap', 'Revenues')])
    assert (v['value'], v['unit'], v['period_end'], v['concept']) == (2, 'USD', '2024-12-31', 'us-gaap:Revenues')
    assert pick({}, 'duration', [('us-gaap', 'Revenues')]) is None
