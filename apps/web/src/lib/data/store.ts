// Read side of the data store: DuckDB over the latest Parquet snapshot written by data/pipeline.
import { DuckDBInstance, type DuckDBConnection } from '@duckdb/node-api';
import { readFile } from 'node:fs/promises';
import path from 'node:path';
import type { DataCatalogEntry } from '@/lib/sim/types';
import type { CompanyProfile, CompanySummary, CountryProfile, CountrySummary, IndicatorValue, Missing, Sourced } from './types';

const TABLES = ['catalog', 'countries', 'country_groups', 'indicators', 'admin1', 'companies', 'company_legal', 'company_sites', 'company_financials'];
/** DuckDB → JSON: dates as YYYY-MM-DD, timestamps as ISO-8601 UTC. Use with `SELECT * EXCLUDE (as_of, retrieved)`. */
const DATES = `CAST(as_of AS VARCHAR) AS as_of, strftime(retrieved, '%Y-%m-%dT%H:%M:%SZ') AS retrieved`;
const PROV = `source, confidence, license, ${DATES}`;
const DAY = 86_400_000;

export class NoSnapshotError extends Error {}

/** Snapshot root. Paths handed to DuckDB are made relative because it treats `*` as a glob and this repo's path contains `**`. */
const root = () => process.env.WORLDSIM_SNAPSHOTS ?? path.resolve(process.cwd(), '../../data/snapshots');
const rel = (p: string) => path.relative(process.cwd(), p);

let conn: Promise<DuckDBConnection> | null = null;
let loaded = '';

async function db() {
  const snapshot = (await readFile(path.join(root(), 'LATEST'), 'utf8').catch(() => '')).trim();
  if (!snapshot) throw new NoSnapshotError('No data snapshot yet. Run `python -m pipeline run` in data/ (see docs/DEMO-M1.md).');
  conn ??= DuckDBInstance.create(':memory:').then((db) => db.connect());
  const c = await conn;
  if (loaded !== snapshot) {
    for (const t of TABLES) {
      const file = rel(path.join(root(), snapshot, `${t}.parquet`)).replaceAll("'", "''");
      await c.run(`CREATE OR REPLACE VIEW ${t} AS SELECT * FROM read_parquet('${file}')`);
    }
    loaded = snapshot;
  }
  return { c, snapshot };
}

/** Route helper: 200 with the value, 404 when null, 503 while no snapshot exists. */
export async function respond(load: () => Promise<unknown>, notFound = 'not found'): Promise<Response> {
  try {
    const v = await load();
    return v == null ? Response.json({ error: notFound }, { status: 404 }) : Response.json(v);
  } catch (e) {
    if (e instanceof NoSnapshotError) return Response.json({ error: e.message }, { status: 503 });
    throw e;
  }
}

type Row = Record<string, unknown>;
async function query<T = Row>(sql: string, params: string[] = []): Promise<{ rows: T[]; snapshot: string }> {
  const { c, snapshot } = await db();
  const res = await c.runAndReadAll(sql, params);
  return { rows: res.getRowObjectsJson() as T[], snapshot };
}

const prov = (r: Row): Sourced => ({ source: r.source, as_of: r.as_of, confidence: r.confidence, license: r.license, retrieved: r.retrieved }) as Sourced;
const PROV_KEYS = new Set(['source', 'as_of', 'confidence', 'license', 'retrieved']);
const strip = (r: Row) => Object.fromEntries(Object.entries(r).filter(([k]) => !PROV_KEYS.has(k)));

export async function getCatalog(now = Date.now()): Promise<DataCatalogEntry[]> {
  const { rows, snapshot } = await query<Omit<DataCatalogEntry, 'freshness' | 'stale' | 'stale_reason' | 'snapshot_id'>>(
    `SELECT * EXCLUDE (as_of, retrieved), ${DATES} FROM catalog ORDER BY id`);
  return rows.map((e) => {
    const age = e.retrieved ? Math.floor((now - Date.parse(e.retrieved)) / DAY) : null;
    const stale_reason =
      e.fetch_status === 'unavailable' ? `Source unavailable and no cached copy: ${e.error ?? 'unknown error'}`
      : e.fetch_status === 'cached' ? `Live fetch failed; served from the cached copy retrieved ${e.retrieved?.slice(0, 10)}`
      : e.fetch_status === 'partial' ? 'Some records could not be fetched and are labeled missing'
      : age !== null && age > e.max_age_days ? `Retrieved ${age} days ago; expected refresh every ${e.max_age_days} days`
      : null;
    return { ...e, snapshot_id: snapshot, freshness: e.fetch_status === 'unavailable' ? 'unavailable' : stale_reason ? 'stale' : 'fresh', stale: !!stale_reason, stale_reason };
  });
}

export async function listCountries(): Promise<{ snapshot_id: string; countries: CountrySummary[] }> {
  const { rows, snapshot } = await query<CountrySummary>(`
    SELECT c.iso3, c.iso2, c.name, c.ne_type AS type, r.label AS region, i.label AS income_group,
           p.value AS population, p.year AS population_year, c.centroid_lat AS lat, c.centroid_lon AS lon
    FROM countries c
    LEFT JOIN country_groups r ON r.iso3 = c.iso3 AND r.scheme = 'wb_region'
    LEFT JOIN country_groups i ON i.iso3 = c.iso3 AND i.scheme = 'wb_income'
    LEFT JOIN (SELECT iso3, arg_max(value, year) AS value, max(year) AS year FROM indicators WHERE key = 'population' GROUP BY iso3) p ON p.iso3 = c.iso3
    ORDER BY c.name`);
  return { snapshot_id: snapshot, countries: rows };
}

export async function getCountry(iso3: string, opts: { series?: boolean } = {}): Promise<CountryProfile | null> {
  const code = iso3.toUpperCase();
  const { rows: [c], snapshot } = await query<Row>(`SELECT * EXCLUDE (geometry, as_of, retrieved), ${DATES} FROM countries WHERE iso3 = ?`, [code]);
  if (!c) return null;
  const [groups, obs, known, admin1] = await Promise.all([
    query<Row>(`SELECT scheme, code, label, ${PROV} FROM country_groups WHERE iso3 = ?`, [code]),
    query<IndicatorValue>(`SELECT key, indicator, name, unit, year, value, ${PROV} FROM indicators WHERE iso3 = ? ORDER BY key, year`, [code]),
    query<{ key: string; name: string }>(`SELECT key, any_value(name) AS name FROM indicators GROUP BY key ORDER BY key`),
    query<Row>(`SELECT CAST(id AS DOUBLE) AS id, name, type, iso_3166_2, lat, lon, ${PROV} FROM admin1 WHERE iso3 = ? ORDER BY name`, [code]),
  ]);

  const indicators: Record<string, IndicatorValue> = {};
  const series: Record<string, { year: number; value: number }[]> = {};
  for (const r of obs.rows) {
    indicators[r.key] = r; // rows are year-ascending, so the latest observation wins
    (series[r.key] ??= []).push({ year: r.year, value: r.value });
  }
  const missing: Missing[] = known.rows.filter((k) => !indicators[k.key]).map((k) => ({ field: `indicators.${k.key}`, reason: `${k.name}: no World Bank observation 2000-2025` }));
  if (!groups.rows.length) missing.push({ field: 'groups', reason: 'Not a World Bank economy: no income group or region' });

  const age_structure = ageStructure(series, indicators);
  if (!age_structure) missing.push({ field: 'age_structure', reason: 'No year with every 5-year band and female/male totals' });

  return {
    snapshot_id: snapshot,
    iso3: c.iso3 as string, iso2: c.iso2 as string | null, name: c.name as string, name_long: c.name_long as string | null,
    formal_name: c.formal_name as string | null, type: c.ne_type as string, sovereign_iso3: c.sovereign_iso3 as string | null,
    continent: c.continent as string | null, subregion: c.subregion as string | null,
    centroid: { lat: c.centroid_lat as number, lon: c.centroid_lon as number },
    label_point: c.label_lat == null ? null : { lat: c.label_lat as number, lon: c.label_lon as number },
    provenance: prov(c),
    groups: Object.fromEntries(groups.rows.map((g) => [g.scheme, { code: g.code, label: g.label, ...prov(g) }])),
    indicators,
    age_structure,
    admin1: admin1.rows.map(strip) as CountryProfile['admin1'],
    admin1_provenance: admin1.rows[0] ? prov(admin1.rows[0]) : null,
    ...(opts.series ? { series } : {}),
    missing,
  };
}

/** People per 5-year band = band share (% of own sex) × female/male total, for the latest year where all of them exist. */
function ageStructure(series: Record<string, { year: number; value: number }[]>, indicators: Record<string, IndicatorValue>): CountryProfile['age_structure'] {
  const bands = Object.keys(series).filter((k) => /^age_\d\d_\w+_female_pct$/.test(k)).sort();
  const needed = [...bands, ...bands.map((k) => k.replace('_female_', '_male_')), 'population_female', 'population_male'];
  if (!bands.length || needed.some((k) => !series[k])) return null;
  const value = (k: string, y: number) => series[k].find((p) => p.year === y)?.value;
  const year = series.population_female.map((p) => p.year).reverse().find((y) => needed.every((k) => value(k, y) !== undefined));
  if (year === undefined) return null;
  return {
    year, unit: 'people', ...prov(indicators[bands[0]] as unknown as Row),
    bands: bands.map((k) => ({
      band: k.replace(/^age_(\d\d)_(\w+)_female_pct$/, (_, a: string, b: string) => (b === 'up' ? `${+a}+` : `${+a}-${+b}`)),
      female: Math.round((value(k, year)! / 100) * value('population_female', year)!),
      male: Math.round((value(k.replace('_female_', '_male_'), year)! / 100) * value('population_male', year)!),
    })),
  };
}

export async function listCompanies(): Promise<{ snapshot_id: string; companies: CompanySummary[] }> {
  const { rows, snapshot } = await query<CompanySummary>(`SELECT id, name, ticker, exchange, country_iso3, industry,
    CAST(employees AS DOUBLE) AS employees, reference FROM companies ORDER BY employees DESC NULLS LAST, name`);
  return { snapshot_id: snapshot, companies: rows };
}

/** Resolve a company by id, Wikidata QID, LEI, ticker, or a unique id prefix ("meta" → "meta-platforms"). */
export async function getCompany(ref: string): Promise<CompanyProfile | null> {
  const r = ref.toLowerCase();
  const { rows: matches, snapshot } = await query<{ id: string }>(`
    SELECT id FROM (SELECT id, 0 AS rank FROM companies WHERE id = $1 OR lower(qid) = $1 OR lower(lei) = $1
      UNION ALL SELECT id, 1 FROM companies WHERE lower(ticker) = $1
      UNION ALL SELECT any_value(id), 2 FROM companies WHERE starts_with(id, $1 || '-') HAVING count(*) = 1)
    ORDER BY rank LIMIT 1`, [r]);
  const id = matches[0]?.id;
  if (!id) return null;
  const [co, legal, sites, fin] = await Promise.all([
    query<Row>(`SELECT * EXCLUDE (employees, employees_as_of, as_of, retrieved), CAST(employees AS DOUBLE) AS employees,
      CAST(employees_as_of AS VARCHAR) AS employees_as_of, ${DATES} FROM companies WHERE id = ?`, [id]),
    query<Row>(`SELECT * EXCLUDE (company_id, as_of, retrieved), ${DATES} FROM company_legal WHERE company_id = ?`, [id]),
    query<Row>(`SELECT * EXCLUDE (company_id, as_of, retrieved), ${DATES} FROM company_sites WHERE company_id = ? ORDER BY source DESC, kind`, [id]),
    query<Row>(`SELECT * EXCLUDE (company_id, period_start, period_end, as_of, retrieved), CAST(period_start AS VARCHAR) AS period_start,
      CAST(period_end AS VARCHAR) AS period_end, ${DATES} FROM company_financials WHERE company_id = ? ORDER BY metric`, [id]),
  ]);
  const c = co.rows[0];
  const l = legal.rows[0] ?? null;
  const financials = Object.fromEntries(fin.rows.map(({ metric, ...f }) => [metric, f])) as CompanyProfile['financials'];

  const missing: Missing[] = [];
  for (const k of ['industry', 'ticker', 'country_iso3', 'website', 'lei', 'cik', 'employees'])
    if (c[k] == null) missing.push({ field: k, reason: 'Not recorded on Wikidata' });
  if (!l) missing.push({ field: 'legal', reason: c.lei ? `LEI ${c.lei} not found in GLEIF` : 'No LEI on Wikidata, so no GLEIF record is linked' });
  if (!sites.rows.some((s) => s.lat != null)) missing.push({ field: 'sites.headquarters', reason: 'No headquarters coordinates on Wikidata' });
  for (const [m, f] of Object.entries(financials)) if (f?.value == null) missing.push({ field: `financials.${m}`, reason: f?.missing_reason ?? 'missing' });

  return {
    ...(strip(c) as Omit<CompanyProfile, 'snapshot_id' | 'provenance' | 'legal' | 'sites' | 'financials' | 'missing'>),
    snapshot_id: snapshot,
    provenance: prov(c),
    legal: l as unknown as CompanyProfile['legal'],
    sites: sites.rows as unknown as CompanyProfile['sites'],
    financials,
    missing,
  };
}
