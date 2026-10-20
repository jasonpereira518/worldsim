# Demo script — Milestone 1 (data layer v1)

Takes about fifteen minutes, most of it the first pipeline run. Needs internet for the live sources; later runs fall back to the on-disk cache.

## 1. Build a snapshot

```bash
cd data
uv venv --python 3.13 .venv && uv pip install --python .venv/bin/python -r requirements.txt
.venv/bin/python -m pipeline run
```

Seven jobs, one per source: Natural Earth admin-0 and admin-1, World Bank WDI and classification, Wikidata companies, GLEIF, SEC EDGAR. Each prints its fetch status (`live`, `cached`, `partial`, `unavailable`) and row count. The rows are then validated against `pipeline/schema.sql` and published to `data/snapshots/<today>/` as Parquet, with `data/snapshots/LATEST` pointing at it. The run ends with the freshness table that `.venv/bin/python -m pipeline status` prints (exit code 1 if anything is stale, so a cron job can alert on it).

Options: `--offline` (cache only), `--companies 50` (smaller company set), `--snapshot ID`. Set `WORLDSIM_CONTACT=you@example.com` to add a contact to the User-Agent, as SEC asks of automated clients. SEC EDGAR is the slow step (one request per filer, throttled to stay under SEC's 10 requests/second).

**Stale flag:** after one online run, disconnect and run `.venv/bin/python -m pipeline run --snapshot offline-demo` again (or use `--offline`). Every job falls back to its cached copy and reports `cached`; the catalog marks it stale and shows the original retrieval date. A source with no cache at all is published as `unavailable`: its rows are absent, everything else is intact, and dependent jobs (GLEIF and EDGAR need Wikidata) say why.

## Reading the snapshot (for services/sim and other consumers)

Format: **Parquet files queried with DuckDB** (no Postgres). Layout, stable from M1 on:

```
data/snapshots/LATEST                     one line: the current snapshot id (e.g. 2026-10-20)
data/snapshots/<id>/manifest.json         {snapshot_id, created, tables: {name: rows}, jobs: {job_id: {status, retrieved, rows, errors}}}
data/snapshots/<id>/<table>.parquet       catalog, countries, country_groups, indicators, admin1,
                                          companies, company_legal, company_sites, company_financials
```

Column names, types and constraints are defined once in `data/pipeline/schema.sql`; every table except `catalog` ends with `source, as_of (DATE), license, retrieved (TIMESTAMP, UTC), confidence ('high'|'medium'|'low')`. Keys: `countries.iso3`, `indicators (iso3, indicator, year)` with the stable short name in `key` (e.g. `population`, `gdp_usd`, `age_00_04_female_pct`), `companies.id` (slug, e.g. `apple`) plus `qid`, `lei`, `cik`; company tables join on `company_id`. `company_financials` has one row per (company, metric); `value` is NULL exactly when `missing_reason` is set. Use the snapshot id as `RunConfig.data_snapshot`.

```python
import duckdb, pathlib
root = pathlib.Path('data/snapshots')  # resolve to the real path: DuckDB treats `*` in paths as a glob
snap = root / (root / 'LATEST').read_text().strip()
con = duckdb.connect()
for t in ('countries', 'indicators', 'companies', 'company_financials'):
    con.execute(f"CREATE VIEW {t} AS SELECT * FROM read_parquet('{snap / (t + '.parquet')}')")
con.sql("SELECT key, year, value FROM indicators WHERE iso3 = 'VNM' AND key = 'population' ORDER BY year DESC LIMIT 1")
```

Pass DuckDB a path without `*` (the old `**Quick Projects` symlink contains one); `data/pipeline/store.py` `latest()` and `parquet()` do this. The same data is served over HTTP by the read API below if a service prefers JSON. Re-read `LATEST` per request (or on a timer) to pick up new snapshots without a restart; snapshots are replaced atomically.

## 2. Read API

```bash
cd apps/web && npm run dev
```

- `/api/data/countries/VNM` — Vietnam: Natural Earth identity, centroid and boundary provenance; World Bank income group and region; the latest observed value of every WDI indicator (population, urbanization, life expectancy, GDP nominal and PPP, GDP per capita, growth, inflation, unemployment, internet, mobile, hospital beds, physicians, Gini), each with its year and `{source, as_of, confidence, license, retrieved}`; people per 5-year age band; the provinces (admin-1); and `missing` for any indicator without an observation. Add `?series=1` for full 2000–2025 series.
- `/api/data/countries` — every country with population, region and income group.
- `/api/data/companies/apple` — Apple: Wikidata identity (ticker, sector, employees, HQ coordinates), the GLEIF legal entity and addresses, and SEC EDGAR revenue, net income, cash and long-term debt from the latest 10-K, each with its XBRL concept, period and filing date. Also accepts a QID (`Q312`), LEI, ticker (`aapl`) or unique prefix (`meta`).
- `/api/data/companies/Q20718` — Samsung Electronics, not an SEC filer: its financials are rows with `value: null` and a reason, also listed in `missing`. Nothing is guessed.
- `/api/data/companies` — the ~500 companies.
- `/api/data/catalog` — every dataset with `as_of`, `retrieved`, license, confidence, row count, fetch status, `freshness` and `stale_reason`.

Before the first snapshot the data routes answer `503` with the command to run.

## 3. Data & assumptions drawer

Open http://localhost:3000.

- Click **Data** in the top bar, or type `/sources` in the chat. The drawer lists every source: name, publisher, license, confidence, as-of and retrieval dates, row count, refresh window. Stale and unavailable entries sort first with a solid black badge and the reason; fresh ones have an outline badge. **Fields and notes** expands what each dataset feeds and its caveats. The chat replies with the snapshot id and any stale sources.
- Run a scenario (e.g. the H5N1 example): the drawer's **Scenario assumptions** section lists the run's assumptions with origin and confidence.
- `Esc` or ✕ closes it; clicking a persona swaps it for the persona drawer.

## 4. Checks

```bash
cd data && .venv/bin/python -m pytest pipeline/tests -q
cd apps/web && npm test && npm run build
```

- `test_loader.py` (offline): rows round-trip with provenance; contract violations (bad ISO3, missing license, unknown confidence, out-of-range centroid, a financial row with neither value nor reason) are rejected and nothing is published; centroid (holes, antimeridian), ISO fixes, id slugs, EDGAR fact selection.
- `test_contracts.py` (latest snapshot), per source: provenance on every row, ISO3 validity, coverage, plausible ranges for every indicator, age bands summing to 100%, Apple's identity, HQ, LEI record and 10-K revenue.
- Vitest: the 17 M0 tests, `GET /api/data/countries/VNM` (real values with provenance, 404/400), and store tests (Apple profile, reference resolution, missing labels, stale flags). The data tests skip when no snapshot exists.
