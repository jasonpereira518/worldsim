# Worldsim — Architecture v0

Status: Milestone 1 (data layer v1). Simulated today (t0) is Tuesday 2026-10-20. Every output is labeled a simulation, not a forecast or advice.

## 1. Principles

1. Numbers come from data or quantitative models. LLMs parse prompts, voice personas, and write prose; an LLM never emits a number the engine did not compute.
2. Every value carries provenance `{source, as_of, confidence, license}`. Missing data becomes a labeled assumption, never a silent invention.
3. The client is a player. It renders a stream of frames, scrubs them, and asks questions. It computes no outcomes.
4. Reproducible: `(seed, ScenarioSpec, data_snapshot)` replays any run bit for bit.
5. Uncertainty is first-class: ensembles report medians with 50% and 90% intervals. The animation shows the median run.

## 2. Repo layout

```
apps/web/                 Next.js 16 · TypeScript · Tailwind v4 · MapLibre GL · useSyncExternalStore store
  src/app/                routes; /api/* implements the sim-service contract (mock engine in M0)
  src/lib/sim/            types.ts (contracts), prng.ts, parse.ts, personas.ts, engine.ts (mock)
  src/lib/map/            style.ts (monochrome basemap + data layers), bubbles.ts (collision layout)
  src/components/         TopBar, MapView, Timeline, ChatPanel, VoicesLog, PersonaDrawer, LayerPills
  data/                   places.json (Natural Earth populated places) + catalog.json (provenance)
  scripts/fetch-places.mjs  seed ETL: download → normalize → data/places.json
services/sim/             M1+  FastAPI: engine, domain modules, persona cognition, reporter
data/pipeline/            M1   Python ETL (stdlib + DuckDB): one job per source → validated Parquet snapshot, catalog with provenance
  schema.sql              logical schema = data contract (NOT NULL provenance, ISO3/range CHECKs)
  jobs/                   naturalearth.py, worldbank.py, companies.py (Wikidata, GLEIF, SEC EDGAR)
  tests/                  test_loader.py (offline), test_contracts.py (per source, latest snapshot)
data/snapshots/<date>/    *.parquet + manifest.json; LATEST names the current snapshot (generated, gitignored)
data/cache/               last good response per request, the fallback when a source is down (gitignored)
apps/web/src/lib/data/    store.ts (DuckDB over the latest snapshot), types.ts (read API contracts)
docs/                     this file, DESIGN.md, DEMO-M0.md
```

Contracts are defined once in `apps/web/src/lib/sim/types.ts`. In M1 the Python side mirrors them as Pydantic models and a contract test checks that the generated JSON Schemas match.

## 3. Data model

```ts
ScenarioSpec   { title, prompt, event_type, domains[], origin: Place|null, global, start_date,
                 horizon_days, step_days, actors[], mechanisms[], assumptions: Assumption[],
                 clarifying_question?, engine: 'mock-m0'|'worldsim', confidence }
Assumption     { id, text, value?, origin: 'data'|'model'|'llm'|'user'|'mock', confidence }
Persona        { id, kind: 'people'|'institution', label, location{lat,lon,admin1,country_iso3,city},
                 population_represented, demographics{...}, traits{...}, context{...}, voice }
Frame          { t, date, deltas: Delta[], bubbles: Bubble[], events: SimEvent[], flows: Flow[], metrics }
Delta          { id, status: PersonaStatus, metric? }        // only personas that changed this step
Bubble         { id, persona_id, t, text (≤140 chars), sentiment, priority, why{event,metric,before,after,unit} }
SimEvent       { id, t, date, title, cause, places[], severity }
Flow           { from:[lon,lat], to:[lon,lat], weight, kind }
RunConfig      { run_id, seed, spec, created_at, data_snapshot, parent_run_id?, branch_at? }
Summary        { headline, metrics[{name,value,unit,low?,high?,confidence}], note }
Provenance     { source, as_of, confidence, license }        // on every catalog entry and data field
```

Persona statuses: `unaware → aware → reacting → affected → recovered`, plus `adopted` / `opposed` for launches and policy. The client stores status per persona per step in a `Uint8Array`, so scrubbing is O(1).

### Store design (M1+)
- Postgres + PostGIS: entities (countries, admin units, companies, sites), relations, run configs, reports.
- Parquet/DuckDB: time series (indicators by iso3 × year, prices, cases). Columnar, cheap, versioned by snapshot id.
- pgvector: entity and analog retrieval. Redis: cache and LLM response cache. Graph queries via Postgres recursive CTEs until a graph DB is justified.
- Every row: `source, as_of, confidence, license`. The catalog is a table, not a doc.

## 4. Module interfaces (Python, M1+)

```python
class DomainModule(Protocol):
    name: str
    def init(self, spec: ScenarioSpec, world: WorldState, rng: Rng) -> ModuleState: ...
    def step(self, state: ModuleState, t: int, world: WorldState, rng: Rng) -> tuple[ModuleState, list[SimEvent]]: ...
    def outputs(self, state: ModuleState) -> dict[str, Series]: ...   # per-entity metrics, with units
    def assumptions(self) -> list[Assumption]: ...                   # everything it took as given

class PersonaCognition(Protocol):
    def perceive_decide_speak(self, personas: list[Persona], view: list[LocalView], budget: Budget) -> list[Reaction]: ...
    # Reaction = {persona_id, decision, emotion, bubble_text, why}; validated against rules before use

class Reporter(Protocol):
    def summarize(self, run: RunArtifacts, ensemble: EnsembleStats) -> Report: ...

class DataAPI(Protocol):   # the only way modules read the world
    def country(self, iso3: str) -> CountryProfile: ...
    def company(self, ref: str) -> CompanyProfile: ...
    def network(self, kind: Literal['air','sea','trade','finance','social']) -> Graph: ...
    def analogs(self, spec: ScenarioSpec, k: int) -> list[Analog]: ...
```

Pipeline per run: `parse → assemble context → select modules → generate personas → step loop (physics → cognition → propagation) → event log + causal graph → ensemble stats → report`.

## 5. API contract

Served by Next.js route handlers in M0 (mock engine). From M2 the same paths proxy to FastAPI; the client does not change.

```
POST /api/runs                 {prompt, answers?, assumptions?, seed?, parent_run_id?, branch_at?}
                               → 201 {run_id, spec}          spec may carry clarifying_question
GET  /api/runs/{id}            → RunConfig
GET  /api/runs/{id}/stream     text/event-stream
       event: personas   data: {personas: Persona[]}           once, before the first frame
       event: frame      data: Frame                           one per step
       event: progress   data: {t, total, label}
       event: summary    data: Summary                         at the end
       event: done | error
POST /api/runs/{id}/chat       {message} → {reply, action?}    action: {type:'zoom', center, zoom} | {type:'branch', run_id}
GET  /api/data/catalog         → DataCatalogEntry[]          as_of, retrieved, license, confidence, fetch_status, freshness, stale_reason
GET  /api/data/countries       → {snapshot_id, countries: CountrySummary[]}
GET  /api/data/countries/{iso3}[?series=1] → CountryProfile  every value {…, source, as_of, confidence, license, retrieved}; `missing[]`
GET  /api/data/companies       → {snapshot_id, companies: CompanySummary[]}
GET  /api/data/companies/{ref} → CompanyProfile              ref = id | QID | LEI | ticker | unique id prefix; `missing[]`
                               data routes: 404 unknown, 400 malformed, 503 before the first snapshot
GET  /api/runs/{id}/report.md | .pdf        (M4)
```

Frames carry deltas only. The `personas` event carries static fields once. A 4k-persona, 180-step run is about 1 MB total.

## 6. Frontend

- **State**: one external store on React's `useSyncExternalStore` (`lib/createStore.ts`, 30 lines; same API shape as Zustand). `run` (spec, personas, frames, statusAt[t]), `playback` (playhead, playing, speed), `ui` (theme, layers, selection, filters), `chat` (messages).
- **Clocks**: server progress ("Simulating day 14 of 120") and the client playhead are independent. The client plays buffered frames at 1×/4×/16× and can scrub any received step.
- **Map**: `buildStyle(theme, data)` returns one MapLibre style containing basemap layers (OpenFreeMap vector tiles, OpenMapTiles schema, monochrome paint) and the data layers. Theme switch = rebuild the style with current data.
  - People = circle layer on a clustered GeoJSON source. `clusterProperties` sums `pop` and `pop × intensity`, so cluster size and shade conserve population and show the weighted mean state.
  - Institutions = symbol layer with one SDF square image; `icon-color` uses the same status expression as circles.
  - Flows = line layer with animated `line-dasharray` (particles); static under reduced motion.
  - Bubbles = HTML overlay; greedy collision layout on every render; cap 6–10 at global zoom, more when zoomed in.
- **Why not deck.gl in M0**: MapLibre renders ~10k clustered points at 60 fps and clusters in a worker. deck.gl arrives in M3 for arcs and particles beyond ~50k features.

## 7. Defaults chosen (stated, not asked)

| Decision | Default | Why |
|---|---|---|
| Basemap tiles | OpenFreeMap (free, no key) | The monochrome style is ours; swap the source URL for self-hosted PMTiles later |
| Fonts | Geist Sans + Geist Mono (npm `geist`, no network at build) | Spec allowed Inter or Geist |
| Package manager | npm | Lowest friction; lockfile committed |
| Mock seed data | Natural Earth 50m populated places (public domain) | Real places and populations; provenance in catalog.json |
| Mock engine location | Next route handlers, same SSE contract as FastAPI | Client code survives the engine swap |
| Determinism | seed = fnv1a(prompt) unless given; mulberry32 PRNG | Reproducible runs from day one |
| Tests | Vitest (unit); Playwright in M3 | Pure-function cores are testable without a browser |
| Dark secondary gray | `#8F8F8F` instead of `#6B6B6B` | `#6B6B6B` on black is 3.9:1 and fails WCAG AA |
| State library | none (React `useSyncExternalStore`) | The project path contains `*`; TypeScript and Vite substitute wildcard `exports` ("./*") into the absolute path, so packages like Zustand fail to resolve here. Rename the parent folder to lift this constraint. |

## 8. Milestone 0: plan and acceptance

Deliverables: repo scaffold, design tokens, monochrome basemap (light/dark), layout, mock data flowing end to end.

Tasks
1. Scaffold `apps/web`; tokens in `globals.css`; fonts; theme toggle with no flash.
2. Seed ETL: `scripts/fetch-places.mjs` → `data/places.json` + `catalog.json`.
3. `lib/sim`: contracts, seeded PRNG, persona generator (population-conserving), prompt parser (keyword + place match), mock diffusion engine.
4. `/api/runs`, `/api/runs/{id}/stream`, `/api/runs/{id}/chat`, `/api/data/catalog`.
5. Map: style builder, clustered dots, SDF squares, flows, bubble overlay, persona drawer, layer pills.
6. Chat panel: prompt → spec card with assumption chips → progress → notable moments → mock summary; `/assumptions`, `/sources`, `/reset`; Voices tab with filters.
7. Timeline: native range scrubber, event markers, play/pause/step/speed.
8. Tests: style is grayscale-only (both themes); persona population conservation; engine determinism; parser on the four example prompts; bubble layout has no overlaps.

Acceptance
- Prompt → animated dots and bubbles in under 15 s; mock summary at the end.
- Strictly white/black/gray UI and map; AA contrast; keyboard operable; reduced motion respected.
- Clustering conserves population; `npm test` and `npm run build` pass.
- Everything mock is labeled "MOCK ENGINE" in the UI and `origin: 'mock'` in assumptions.

## 9. Milestones 1–5

1. **Done.** Data layer v1: World Bank WDI, UN WPP, Natural Earth admin-0/1, GLEIF + Wikidata + EDGAR for ~500 companies; Postgres/PostGIS + Parquet; catalog with provenance; freshness jobs. See "M1 as built" below and `docs/DEMO-M1.md`.
2. FastAPI service; LLM scenario parser with JSON-schema outputs; persona generator from real distributions; product-launch module (Bass diffusion × price elasticity × supply); persona cognition with a budget manager; summary report. Walkthrough A end to end.
3. Epidemiology (age-structured SEIRD + air-travel coupling), disaster, macro/supply-chain modules; networks layer; ensembles (20–100 runs) with 50/90% bands; deck.gl for arcs and particles.
4. Branching, compare view, real-time feeds (GDELT, markets, USGS, WHO DON), generic fallback module, PDF/Markdown export, shareable links.
5. Calibration and backtests against analogs, performance tuning, accessibility audit, docs.

### M1 as built

`python -m pipeline run` (in `data/`) runs seven jobs, one per source, and publishes snapshot `data/snapshots/<YYYY-MM-DD>/`:

| Job (catalog id) | Source · license | Tables | Rows (2026-10-20) |
|---|---|---|---|
| `ne_admin0_50m` | Natural Earth v5.1.2 · public domain | `countries` (ISO3 key, centroid, label point, GeoJSON boundary) | 237 countries and territories |
| `ne_admin1_10m` | Natural Earth v5.1.2 · public domain | `admin1` | 4,567 regions |
| `wb_wdi` | World Bank WDI · CC BY 4.0 | `indicators` (long format: iso3 × indicator × year, 2000–2025, 53 series) | 284,050 observations, 216 economies |
| `wb_classification` | World Bank Country API · CC BY 4.0 | `country_groups` (income group, region, lending type) | 648 |
| `wikidata_companies` | Wikidata · CC0 | `companies`, `company_sites` (HQ with coordinates) | 500 companies; 499 with headcount, 498 with HQ coordinates, 483 with a ticker |
| `gleif_lei` | GLEIF · CC0 | `company_legal`, `company_sites` (HQ and legal addresses) | 421 legal entities (the companies with an LEI on Wikidata) |
| `sec_edgar_companyfacts` | SEC EDGAR · public domain | `company_financials` (revenue, net income, cash, long-term debt, headcount; latest annual filing) | 2,500 rows: revenue for 185 of the 225 companies with a CIK; the rest labeled missing with a reason |

- **Provenance and contract.** Every row carries `source, as_of, confidence, license, retrieved`. `schema.sql` enforces it (NOT NULL, CHECKs on ISO3, confidence, coordinate ranges, "value or missing_reason"); a violating snapshot is never published. `pytest` contract tests then check coverage and plausible ranges per source.
- **Missing, never guessed.** Indicators are stored only where observed; the API lists unobserved keys in `missing`. GLEIF and EDGAR are joined only on the LEI and CIK recorded in Wikidata (no name matching); a company without one gets explicit `missing` entries with the reason.
- **Freshness.** Each request is cached (`data/cache/`). If a live fetch fails the job uses the last good copy and reports `cached`; if some records have neither it reports `partial`; with nothing at all it is `unavailable` and its tables are empty. The catalog stores the status, retrieval time and refresh window (`max_age_days`); `/api/data/catalog` and `python -m pipeline status` flag stale entries. Schedule `python -m pipeline run` (cron, or a CI job) as the freshness job.
- **Read path.** `apps/web/src/lib/data/store.ts` opens the Parquet files of `data/snapshots/LATEST` with DuckDB (`@duckdb/node-api`, server-external) and re-points its views when LATEST changes, so a new snapshot is live without a restart.

Deviations from the plan above, with the reason:

1. **No Postgres/PostGIS yet.** No Postgres in the dev environment, so the store is Parquet + DuckDB for every table (the brief's stated fallback). `schema.sql` is Postgres-portable (swap `regexp_full_match` for `~`, GeoJSON text for `geometry`); move entities to Postgres/PostGIS when the FastAPI service needs spatial queries or writes (M2+).
2. **No Dagster.** Seven plain job functions and a CLI; dependencies between jobs are explicit (`ctx`). Revisit if jobs need independent schedules.
3. **UN WPP via WDI.** Age structure uses the WPP five-year band shares that WDI republishes (`SP.POP.<band>.FE/MA.5Y`) × female/male totals, not a WPP bulk download.
4. **Company selection.** The ~500 are the listed, non-dissolved companies with the most employees on Wikidata, plus the 11 reference-walkthrough companies. Forbes Global 2000 is not openly licensed. Financials stay in the reported currency (no FX conversion yet).
5. **Admin-1 at 1:10m.** The 1:50m admin-1 layer covers only a handful of countries. Conversely, Gibraltar (GIB) has World Bank data but no 1:50m admin-0 shape, so `/api/data/countries/GIB` is a 404 until boundaries move to 1:10m.
6. **The mock engine still runs on M0 data.** Runs keep `data_snapshot: 'm0-natural-earth-5.1.1'`; the engine reads the store from M2.
7. **Pydantic mirror deferred.** The JSON-schema contract test between `types.ts` and Python models moves to M2 with the FastAPI service. The read API contracts live in `apps/web/src/lib/data/types.ts`.
8. **Snapshots are generated, not committed.** `data/snapshots/` and `data/cache/` are gitignored; data tests (pytest contracts, vitest route/store) skip until a snapshot exists.
9. **Wikidata query shape.** Six flat SPARQL queries for all companies at once: the query service overflowed on GROUP BY over a large VALUES block, and it rate-limits bursts (down to 1 request/minute during incidents), which the fetcher honors via `Retry-After`.

## 10. Open decisions

None blocking. Revisit at M1: hosting (Vercel for web and light API; the sim service on a container host), graph store (Postgres CTEs vs Neo4j), LLM provider via a gateway.
