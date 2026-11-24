"""Data-contract tests per source, run against the latest published snapshot (python -m pipeline run first).
schema.sql already rejects missing provenance and malformed keys at load time; these check coverage and plausibility."""
import duckdb
import pytest

from pipeline.jobs.companies import REFERENCE
from pipeline.jobs.worldbank import PLAUSIBLE
from pipeline.store import latest, parquet

SNAP = latest()
pytestmark = pytest.mark.skipif(SNAP is None, reason='no snapshot yet: run `python -m pipeline run`')
PROVENANCE = ['source', 'as_of', 'confidence', 'license', 'retrieved']
TABLES = ['catalog', 'countries', 'country_groups', 'indicators', 'admin1', 'companies', 'company_legal', 'company_sites', 'company_financials']


def sql(q: str):
    for t in TABLES:
        q = q.replace(f'{{{t}}}', f"read_parquet('{parquet(SNAP, t)}')")
    return duckdb.sql(q).fetchall()


def full_run() -> bool:
    return sql('SELECT count(*) FROM {companies}')[0][0] >= 400


@pytest.mark.parametrize('table', TABLES[1:])
def test_every_row_has_provenance(table):
    nulls = ' OR '.join(f'{c} IS NULL' for c in PROVENANCE)
    assert sql(f'SELECT count(*) FROM {{{table}}} WHERE {nulls}')[0][0] == 0
    assert sql(f"SELECT count(*) FROM {{{table}}} WHERE confidence NOT IN ('high', 'medium', 'low')")[0][0] == 0


def test_catalog_lists_every_source():
    rows = {r[0]: r[1:] for r in sql('SELECT id, license, confidence, fetch_status, as_of FROM {catalog}')}
    assert set(rows) >= {'ne_admin0_50m', 'ne_admin1_10m', 'wb_wdi', 'wb_classification', 'wikidata_companies', 'gleif_lei',
                         'sec_edgar_companyfacts', 'ne_populated_places_50m'}
    for id_, (license_, confidence, status, as_of) in rows.items():
        assert license_ and confidence, id_
        assert status == 'unavailable' or as_of is not None, id_


# Natural Earth admin-0
def test_countries():
    n, bad_iso, vnm = sql("""SELECT count(*), count(*) FILTER (WHERE NOT regexp_full_match(iso3, '[A-Z]{3}')),
                             count(*) FILTER (WHERE iso3 = 'VNM' AND centroid_lat BETWEEN 8 AND 24 AND centroid_lon BETWEEN 102 AND 110)
                             FROM {countries}""")[0]
    assert n >= 230 and bad_iso == 0 and vnm == 1
    assert sql("SELECT count(*) FROM {countries} WHERE ne_type IN ('Sovereign country', 'Country')")[0][0] >= 190
    assert sql("SELECT iso3 FROM {countries} WHERE iso3 IN ('FRA', 'NOR', 'XKX') ORDER BY 1") == [('FRA',), ('NOR',), ('XKX',)]


# Natural Earth admin-1
def test_admin1():
    n, orphans = sql("""SELECT count(*), count(*) FILTER (WHERE iso3 NOT IN (SELECT iso3 FROM {countries})) FROM {admin1}""")[0]
    assert n >= 3500 and orphans == 0
    assert sql("SELECT count(*) FROM {admin1} WHERE iso3 = 'VNM'")[0][0] >= 50


# World Bank classification
def test_country_groups():
    assert sql("SELECT count(DISTINCT iso3) FROM {country_groups} WHERE scheme = 'wb_income'")[0][0] >= 210
    codes = {r[0] for r in sql("SELECT DISTINCT code FROM {country_groups} WHERE scheme = 'wb_income'")}
    assert codes <= {'LIC', 'LMC', 'UMC', 'HIC', 'INX'}


# World Bank WDI
@pytest.mark.parametrize('key,lo,hi', [(k, lo, hi) for k, (lo, hi) in PLAUSIBLE.items()] + [('age_%_pct', 0, 100)])
def test_indicator_ranges(key, lo, hi):
    """Out-of-range values are source anomalies: kept as published, but they must be flagged low confidence and rare
    (a unit or scaling bug would push many rows out of range at once)."""
    out = sql(f"""SELECT count(*) FILTER (WHERE NOT value BETWEEN {lo} AND {hi}),
                         count(*) FILTER (WHERE NOT value BETWEEN {lo} AND {hi} AND confidence <> 'low'), count(*)
                  FROM {{indicators}} WHERE key LIKE '{key}'""")[0]
    outside, unflagged, total = out
    assert total > 0 and unflagged == 0 and outside <= max(3, total * 0.001), f'{key}: {outside} of {total} outside [{lo}, {hi}], {unflagged} not flagged'


def test_indicator_coverage_and_keys():
    assert sql("SELECT count(DISTINCT key) FROM {indicators}")[0][0] == 20 + 34
    assert sql("SELECT count(DISTINCT iso3) FROM {indicators} WHERE key = 'population'")[0][0] >= 210
    year, pop = sql("SELECT year, value FROM {indicators} WHERE iso3 = 'VNM' AND key = 'population' ORDER BY year DESC LIMIT 1")[0]
    assert year >= 2024 and 9e7 < pop < 1.2e8


def test_age_bands_sum_to_100():
    out = sql("""SELECT iso3, year, sum(value) s FROM {indicators} WHERE key LIKE 'age_%_female_pct'
                 GROUP BY iso3, year HAVING count(*) = 17 AND abs(s - 100) > 1 LIMIT 5""")
    assert out == []


# Wikidata
def test_companies():
    n, ids = sql("SELECT count(*), count(DISTINCT id) FROM {companies}")[0]
    assert n == ids
    assert {r[0] for r in sql('SELECT qid FROM {companies} WHERE reference')} == set(REFERENCE)
    apple = sql("SELECT id, ticker, country_iso3, cik, lei, employees FROM {companies} WHERE qid = 'Q312'")[0]
    assert apple[:5] == ('apple', 'AAPL', 'USA', '0000320193', 'HWUPKR0MPOU8FGXBT394') and apple[5] > 100_000
    assert sql("SELECT count(*) FROM {companies} WHERE employees > 5e6")[0][0] == 0
    if full_run():
        assert n >= 450
        assert sql("SELECT count(*) FROM {companies} WHERE country_iso3 IS NOT NULL")[0][0] / n > 0.9


def test_company_sites():
    assert sql("SELECT count(*) FROM {company_sites} WHERE company_id NOT IN (SELECT id FROM {companies})")[0][0] == 0
    lat, lon = sql("SELECT lat, lon FROM {company_sites} WHERE company_id = 'apple' AND source = 'Wikidata'")[0]
    assert 36 < lat < 38 and -123 < lon < -121  # Cupertino


# GLEIF
def test_company_legal():
    assert sql("SELECT legal_name, entity_status FROM {company_legal} WHERE company_id = 'apple'") == [('Apple Inc.', 'ACTIVE')]
    assert sql("SELECT count(*) FROM {company_legal} l JOIN {companies} c ON c.id = l.company_id WHERE c.lei <> l.lei")[0][0] == 0


# SEC EDGAR
def test_company_financials():
    assert sql("SELECT count(*) FROM {company_financials} WHERE (value IS NULL) = (missing_reason IS NULL)")[0][0] == 0
    assert sql("SELECT count(*) FROM {companies}")[0][0] * 5 == sql("SELECT count(*) FROM {company_financials}")[0][0]
    rev = sql("SELECT value, unit, form, period_end FROM {company_financials} WHERE company_id = 'apple' AND metric = 'revenue'")[0]
    assert 2e11 < rev[0] < 1e12 and rev[1] == 'USD' and rev[2].startswith('10-K') and str(rev[3]) >= '2024-09-01'
    assert sql("SELECT count(*) FROM {company_financials} WHERE metric = 'revenue' AND value <= 0")[0][0] == 0
