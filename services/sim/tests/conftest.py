"""Builds a small synthetic snapshot (source 'test fixture') so tests run offline and never depend on the live store."""
import json
import os
import tempfile
from pathlib import Path

import duckdb

ROOT = Path(tempfile.mkdtemp(prefix='worldsim-fixture-'))
SNAP = ROOT / 'fixture'
SNAP.mkdir()
(ROOT / 'LATEST').write_text('fixture\n')
os.environ['WORLDSIM_SNAPSHOTS'] = str(ROOT)
os.environ['WORLDSIM_RUNS'] = str(ROOT / 'runs')
os.environ['WORLDSIM_FRAME_DELAY'] = '0'
os.environ['WORLDSIM_ENSEMBLE'] = '8'
os.environ['WORLDSIM_LLM'] = 'off'

# iso3, name, lat, lon, income group, population, urban %, gdp per capita, gini, internet %, beds per 1000, physicians per 1000, age 0-14 %, 65+ %
C = [
    ('USA', 'United States of America', 39.5, -98.5, 'High income', 336e6, 83, 82000, 41, 92, 2.8, 3.6, 17.5, 17.7),
    ('JPN', 'Japan', 36.2, 138.3, 'High income', 124e6, 92, 34000, 33, 87, 12.6, 2.6, 11.6, 29.9),
    ('KOR', 'South Korea', 36.5, 127.9, 'High income', 51.7e6, 81, 33000, 31, 97, 12.8, 2.6, 11.2, 18.5),
    ('DEU', 'Germany', 51.1, 10.4, 'High income', 84e6, 78, 52000, 32, 92, 7.8, 4.5, 14.0, 22.4),
    ('FRA', 'France', 46.6, 2.4, 'High income', 68e6, 82, 46000, 31, 86, 5.7, 3.3, 16.8, 21.7),
    ('BEL', 'Belgium', 50.6, 4.6, 'High income', 11.8e6, 98, 53000, 26, 94, 5.5, 3.2, 16.5, 19.6),
    ('CHN', 'China', 35.0, 103.0, 'Upper middle income', 1410e6, 65, 12600, 37, 77, 4.3, 2.4, 16.8, 14.3),
    ('VNM', 'Vietnam', 16.0, 106.0, 'Lower middle income', 100e6, 39, 4300, 36, 79, 3.2, 0.9, 22.8, 9.4),
    ('THA', 'Thailand', 15.1, 101.0, 'Upper middle income', 71.8e6, 53, 7100, 35, 88, 2.1, 0.9, 15.4, 15.1),
    ('TUR', 'Turkey', 39.0, 35.0, 'Upper middle income', 85e6, 77, 13100, 44, 86, 3.0, 2.2, 21.7, 10.2),
    ('NGA', 'Nigeria', 9.1, 8.7, 'Lower middle income', 224e6, 54, 1600, 35, 55, 0.5, 0.4, 42.5, 2.9),
]
PROV = {'source': 'test fixture', 'as_of': '2026-10-01', 'license': 'test', 'retrieved': '2026-10-20 00:00:00', 'confidence': 'medium'}


def _write(con, name, ddl, rows):
    con.execute(f'CREATE TABLE {name} ({ddl})')
    if rows:
        cols = list(rows[0].keys())
        con.executemany(f'INSERT INTO {name} ({", ".join(cols)}) VALUES ({", ".join("?" for _ in cols)})', [[r[c] for c in cols] for r in rows])
    con.execute(f"COPY {name} TO '{SNAP / (name + '.parquet')}' (FORMAT parquet)")


P = 'source VARCHAR, as_of DATE, license VARCHAR, retrieved TIMESTAMP, confidence VARCHAR'
con = duckdb.connect()
_write(con, 'countries', f'iso3 VARCHAR, name VARCHAR, centroid_lat DOUBLE, centroid_lon DOUBLE, label_lat DOUBLE, label_lon DOUBLE, ne_type VARCHAR, continent VARCHAR, subregion VARCHAR, {P}',
       [dict(iso3=c[0], name=c[1], centroid_lat=c[2], centroid_lon=c[3], label_lat=c[2], label_lon=c[3], ne_type='Sovereign country', continent='', subregion='', **PROV) for c in C])
_write(con, 'country_groups', f'iso3 VARCHAR, scheme VARCHAR, code VARCHAR, label VARCHAR, {P}',
       [dict(iso3=c[0], scheme='wb_income', code=c[4][:3].upper(), label=c[4], **PROV) for c in C])
KEYS = ['population', 'urban_pct', 'gdp_per_capita_usd', 'gini', 'internet_users_pct', 'hospital_beds_per1000', 'physicians_per1000', 'age_0_14_pct', 'age_65_plus_pct']
_write(con, 'indicators', f'iso3 VARCHAR, indicator VARCHAR, key VARCHAR, name VARCHAR, unit VARCHAR, year INTEGER, value DOUBLE, {P}',
       [dict(iso3=c[0], indicator=k, key=k, name=k, unit='', year=2024, value=float(c[5 + i]), **PROV) for c in C for i, k in enumerate(KEYS)])
COMP = [('apple', 'Apple Inc.', 'USA', 37.33, -122.03, 164000, 391e9), ('meta-platforms', 'Meta Platforms', 'USA', 37.48, -122.15, 67000, 135e9),
        ('samsung-electronics', 'Samsung Electronics', 'KOR', 37.26, 127.03, 109000, None), ('sony', 'Sony Group', 'JPN', 35.62, 139.74, 112000, None),
        ('tsmc', 'TSMC', 'TWN', 24.77, 121.0, 65000, None), ('foxconn', 'Foxconn', 'TWN', 25.06, 121.45, 618000, None),
        ('best-buy', 'Best Buy', 'USA', 44.86, -93.32, 85000, 43e9), ('byd', 'BYD Company', 'CHN', 22.6, 114.05, 700000, None),
        ('volkswagen', 'Volkswagen Group', 'DEU', 52.43, 10.79, 672000, None), ('lufthansa', 'Lufthansa', 'DEU', 50.05, 8.57, 100000, None),
        ('maersk', 'Maersk', 'DNK', 55.69, 12.6, 80000, None)]
_write(con, 'companies', f'id VARCHAR, name VARCHAR, industry VARCHAR, country_iso3 VARCHAR, employees BIGINT, reference BOOLEAN, ticker VARCHAR, {P}',
       [dict(id=c[0], name=c[1], industry='', country_iso3=c[2], employees=c[5], reference=True, ticker=None, **PROV) for c in COMP])
_write(con, 'company_sites', f'company_id VARCHAR, kind VARCHAR, city VARCHAR, lat DOUBLE, lon DOUBLE, {P}',
       [dict(company_id=c[0], kind='headquarters', city=c[1], lat=c[3], lon=c[4], **PROV) for c in COMP])
_write(con, 'company_financials', f'company_id VARCHAR, metric VARCHAR, value DOUBLE, unit VARCHAR, period_end DATE, {P}',
       [dict(company_id=c[0], metric='revenue', value=c[6], unit='USD', period_end='2025-09-27', **PROV) for c in COMP if c[6]])
_write(con, 'catalog', 'id VARCHAR, name VARCHAR, source VARCHAR, as_of DATE, license VARCHAR, confidence VARCHAR, fetch_status VARCHAR',
       [dict(id='fixture', name='Test fixture snapshot', source='test fixture', as_of='2026-10-01', license='test', confidence='medium', fetch_status='live')])
(SNAP / 'manifest.json').write_text(json.dumps({'snapshot_id': 'fixture'}))
