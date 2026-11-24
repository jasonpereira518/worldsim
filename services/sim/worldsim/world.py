"""World state at t0: countries, indicators, places and companies from the Milestone 1 snapshot.

The only way modules read the world. Missing values stay None and callers label any prior they use instead.
"""
from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import duckdb

_HERE = Path(__file__).resolve()
# repository root in a checkout (services/sim/worldsim/world.py); inside the container every path comes from env vars
ROOT = _HERE.parents[3] if len(_HERE.parents) > 3 else _HERE.parent
SNAPSHOTS = Path(os.environ.get('WORLDSIM_SNAPSHOTS', ROOT / 'data' / 'snapshots'))
PLACES_JSON = Path(os.environ.get('WORLDSIM_PLACES', ROOT / 'apps' / 'web' / 'data' / 'places.json'))
GAZETTEER_JSON = Path(os.environ.get('WORLDSIM_GAZETTEER', PLACES_JSON.with_name('gazetteer.json')))


@dataclass
class Value:
    value: float
    year: int | None
    source: str
    as_of: str | None
    unit: str = ''

    def ref(self) -> str:
        return f'{self.source} ({self.year})' if self.year else self.source


@dataclass
class Country:
    iso3: str
    name: str
    lat: float
    lon: float
    kind: str = 'Sovereign country'
    continent: str = ''
    subregion: str = ''
    income_group: str | None = None
    ind: dict[str, Value] = field(default_factory=dict)

    def get(self, key: str) -> float | None:
        v = self.ind.get(key)
        return v.value if v else None

    @property
    def population(self) -> float | None:
        return self.get('population')


@dataclass
class City:
    id: int
    name: str
    iso3: str
    admin1: str
    lat: float
    lon: float
    pop: float
    capital: bool
    hub: bool
    country: str


@dataclass
class Company:
    id: str
    name: str
    industry: str | None
    country_iso3: str | None
    lat: float | None
    lon: float | None
    city: str | None
    employees: float | None
    reference: bool
    financials: dict[str, Value] = field(default_factory=dict)
    ticker: str | None = None
    source: str = ''


@dataclass
class World:
    snapshot_id: str
    countries: dict[str, Country]
    cities: list[City]
    companies: dict[str, Company]
    catalog: list[dict]
    available: bool  # False when no snapshot exists: indicator-driven modules fall back to labeled priors
    path: Path | None = None

    def city_by_name(self) -> dict[str, City]:
        out: dict[str, City] = {}
        for c in self.cities:
            k = c.name.lower()
            if k not in out or out[k].pop < c.pop:
                out[k] = c
        return out


def _latest_snapshot() -> Path | None:
    latest = SNAPSHOTS / 'LATEST'
    if latest.exists():
        p = SNAPSHOTS / latest.read_text().strip()
        if (p / 'countries.parquet').exists():
            return p
    return None


def _q(con, path: Path, table: str, sql: str) -> list[tuple]:
    f = path / f'{table}.parquet'
    if not f.exists():
        return []
    return con.execute(sql.replace('{t}', f"read_parquet('{f.as_posix()}')")).fetchall()


def _load_cities() -> list[City]:
    raw = json.loads(PLACES_JSON.read_text())
    return [City(id=p['id'], name=p['name'], iso3=p['iso3'], admin1=p.get('admin1') or '', lat=p['lat'], lon=p['lon'],
                 pop=float(p['pop']), capital=p['capital'], hub=p['hub'], country=p['country']) for p in raw]


@lru_cache(maxsize=1)
def gazetteer() -> list[tuple[tuple[str, ...], City]]:
    """Lookup-only places (Natural Earth 1:10m, pop ≥ 50k; apps/web/scripts/fetch-gazetteer.mjs) with their names: finds
    origins the persona seed lacks without placing personas there. Empty when the file is absent."""
    if not GAZETTEER_JSON.exists():
        return []
    return [((p['name'], p['ascii']) if p.get('ascii') else (p['name'],),
             City(id=p['id'], name=p['name'], iso3=p['iso3'], admin1=p.get('admin1') or '', lat=p['lat'], lon=p['lon'],
                  pop=float(p['pop']), capital=False, hub=False, country=p['country']))
            for p in json.loads(GAZETTEER_JSON.read_text())['places']]


def load_world(snapshot_dir: Path | None = None) -> World:
    cities = _load_cities()
    path = snapshot_dir or _latest_snapshot()
    if path is None:
        # No snapshot: countries from places only, every indicator missing.
        countries: dict[str, Country] = {}
        for c in cities:
            countries.setdefault(c.iso3, Country(iso3=c.iso3, name=c.country, lat=c.lat, lon=c.lon))
        return World('none', countries, cities, {}, [], available=False)

    con = duckdb.connect()
    countries = {r[0]: Country(iso3=r[0], name=r[1], lat=r[2], lon=r[3], kind=r[4], continent=r[5] or '', subregion=r[6] or '')
                 for r in _q(con, path, 'countries', 'SELECT iso3, name, coalesce(label_lat, centroid_lat), coalesce(label_lon, centroid_lon), ne_type, continent, subregion FROM {t}')}
    for iso3, code, label in _q(con, path, 'country_groups', "SELECT iso3, code, label FROM {t} WHERE scheme IN ('income', 'wb_income')"):
        if iso3 in countries:
            countries[iso3].income_group = label
    rows = _q(con, path, 'indicators', """
        SELECT iso3, key, value, year, source, CAST(as_of AS VARCHAR), unit FROM (
          SELECT *, row_number() OVER (PARTITION BY iso3, key ORDER BY year DESC) rn FROM {t}) WHERE rn = 1""")
    for iso3, key, value, year, source, as_of, unit in rows:
        if iso3 in countries:
            countries[iso3].ind[key] = Value(float(value), int(year), source, as_of, unit)
    # Cities whose iso3 is not a snapshot country still need a home.
    for c in cities:
        countries.setdefault(c.iso3, Country(iso3=c.iso3, name=c.country, lat=c.lat, lon=c.lon))

    sites = {r[0]: r[1:] for r in _q(con, path, 'company_sites',
             "SELECT company_id, lat, lon, city FROM {t} WHERE lat IS NOT NULL ORDER BY kind = 'headquarters' DESC")[::-1]}
    companies: dict[str, Company] = {}
    for cid, name, industry, iso3, emp, ref, ticker, source in _q(con, path, 'companies',
            'SELECT id, name, industry, country_iso3, employees, reference, ticker, source FROM {t}'):
        lat, lon, city = sites.get(cid, (None, None, None))
        companies[cid] = Company(cid, name, industry, iso3, lat, lon, city, float(emp) if emp else None, bool(ref), ticker=ticker, source=source)
    for cid, metric, value, unit, period_end, source in _q(con, path, 'company_financials',
            'SELECT company_id, metric, value, unit, CAST(period_end AS VARCHAR), source FROM {t} WHERE value IS NOT NULL'):
        if cid in companies:
            companies[cid].financials[metric] = Value(float(value), int(period_end[:4]) if period_end else None, source, period_end, unit or '')
    catalog = [dict(zip(['id', 'name', 'source', 'as_of', 'license', 'confidence', 'fetch_status'], r)) for r in
               _q(con, path, 'catalog', 'SELECT id, name, source, CAST(as_of AS VARCHAR), license, confidence, fetch_status FROM {t}')]
    return World(path.name, countries, cities, companies, catalog, available=True, path=path)


@lru_cache(maxsize=1)
def world() -> World:
    return load_world()


def haversine_km(lat1, lon1, lat2, lon2):
    """Vectorizes over numpy arrays."""
    import numpy as np
    r = math.pi / 180
    dlat = (np.asarray(lat2) - lat1) * r
    dlon = (np.asarray(lon2) - lon1) * r
    a = np.sin(dlat / 2) ** 2 + math.cos(lat1 * r) * np.cos(np.asarray(lat2) * r) * np.sin(dlon / 2) ** 2
    return 2 * 6371 * np.arcsin(np.sqrt(a))


def _ring_area_km2(ring: list) -> float:
    """Planar shoelace on an equirectangular projection scaled at the ring's mean latitude (adequate for province areas)."""
    if len(ring) < 3:
        return 0.0
    lat0 = math.radians(sum(pt[1] for pt in ring) / len(ring))
    kx, ky = 111.32 * math.cos(lat0), 110.57
    a = 0.0
    for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1]):
        a += (x1 * kx) * (y2 * ky) - (x2 * kx) * (y1 * ky)
    return abs(a) / 2


def _geom_area(geom: dict) -> float:
    polys = [geom['coordinates']] if geom['type'] == 'Polygon' else geom['coordinates'] if geom['type'] == 'MultiPolygon' else []
    total = 0.0
    for poly in polys:
        if poly:
            total += _ring_area_km2([tuple(p[:2]) for p in poly[0]]) - sum(_ring_area_km2([tuple(p[:2]) for p in h]) for h in poly[1:])
    return max(total, 0.0)


@lru_cache(maxsize=4)
def admin1(path: Path | None = None) -> list[tuple[str, str, float, float, float]]:
    """(iso3, name, lat, lon, area_km2) for every admin-1 unit in the snapshot; empty when unavailable."""
    if path is None or not (path / 'admin1.parquet').exists():
        return []
    con = duckdb.connect()
    rows = _q(con, path, 'admin1', 'SELECT iso3, name, lat, lon, geometry FROM {t}')
    return [(iso3, name, float(lat), float(lon), _geom_area(json.loads(g))) for iso3, name, lat, lon, g in rows]
