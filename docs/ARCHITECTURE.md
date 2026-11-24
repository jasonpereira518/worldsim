# Worldsim — Architecture v0

Status: Milestone 6 (agents layer and scale). Simulated today (t0) is Tuesday 2026-10-20. Every output is labeled a simulation, not a forecast or advice.

## 1. Principles

1. Numbers come from data or quantitative models. Agents choose and judge; the engine computes. An agent may place a parameter inside a range defined in code (it becomes a prior with origin `llm`, clamped, cited and editable), but no agent states an outcome or a probability, and prose with a number absent from its inputs is cut.
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
services/sim/             M2–M5  FastAPI simulation service (Python 3.13, NumPy, DuckDB, Pydantic, Anthropic SDK)
  worldsim/world.py       reads the snapshot (countries, indicators, companies, admin-1 areas); nothing is guessed
  worldsim/personas.py    population-conserving segments from age shares + a GDP/Gini lognormal income model
  worldsim/modules/       launch, epidemiology, disaster (earthquake), trade, generic — one interface (base.py)
  worldsim/engine.py      ensemble → median run → frames → sensitivity → counterfactuals → summary
  worldsim/voices.py      grounded bubble templates + validated LLM batches; llm.py budget, cache, cost
  worldsim/report.py      the 11-section report (JSON + Markdown); chat.py follow-ups; compare.py; feeds.py
  worldsim/prompts/       versioned prompt files; tests/ (unit, contract, module, golden runs, backtests)
data/pipeline/            M1   Python ETL (stdlib + DuckDB): one job per source → validated Parquet snapshot, catalog with provenance
  schema.sql              logical schema = data contract (NOT NULL provenance, ISO3/range CHECKs)
  jobs/                   naturalearth.py, worldbank.py, companies.py (Wikidata, GLEIF, SEC EDGAR)
  tests/                  test_loader.py (offline), test_contracts.py (per source, latest snapshot)
data/snapshots/<date>/    *.parquet + manifest.json; LATEST names the current snapshot (generated, gitignored)
data/cache/               last good response per request, the fallback when a source is down (gitignored)
apps/web/src/lib/data/    store.ts (DuckDB over the latest snapshot), types.ts (read API contracts)
docs/                     this file, DESIGN.md, DEMO-M0.md … DEMO-M5.md
docker-compose.yml        pipeline (on demand), sim, web; .github/workflows/ci.yml runs all three test suites
```

Contracts are defined once in `apps/web/src/lib/sim/types.ts` and mirrored by `services/sim/worldsim/models.py`. `services/sim/tests/test_contract.py` parses the TypeScript interfaces and fails when either side adds a field the other does not declare, or when a required TypeScript field is never sent.

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

Next.js route handlers proxy `/api/runs/*`, `/api/health` and `/api/feeds` to the sim service (`SIM_SERVICE_URL`, default `http://127.0.0.1:8731`). When the service is unreachable, run creation, streaming and chat fall back to the M0 mock engine, which labels itself `engine: 'mock-m0'` in the UI. The client does not change.

```
POST /api/runs                 {prompt, answers?, assumptions?, seed?, parent_run_id?, branch_at?}
                               → 201 {run_id, spec}          spec may carry clarifying_question
GET  /api/runs/{id}            → RunConfig
GET  /api/runs/{id}/stream     text/event-stream
       event: personas   data: {personas: Persona[]}           once, before the first frame
       event: meta       data: {meta: RunMeta}                 module, key metric, layers, ensemble size
       event: progress   data: {t, total, label}               "Running ensemble 8 of 24", "Simulating day 14 of 120"
       event: frame      data: Frame                           one per step: deltas, bubbles, events, flows, metrics, layers, band
       event: summary    data: Summary                         medians with 5/25/75/95th percentiles
       event: report     data: Report                          the 11-section report
       event: done | error
GET  /api/runs                 → RunListItem[]               run history with parent links (branches)
POST /api/runs/{id}/chat       {message, t?} → {reply, action?}
                               action: zoom {center, zoom} | layers {…} | branch {run_id, spec, parent_run_id} | compare {a, b}
GET  /api/runs/{id}/report     → Report;  GET /api/runs/{id}/report.md → Markdown download
GET  /api/runs/{a}/compare/{b} → CompareResult              metric deltas with intervals, both bands, country deltas
GET  /api/feeds                → {feeds: [{id, name, publisher, license, retrieved, status: live|stale|unavailable, items}]}
GET  /api/data/geo             → country polygons (FeatureCollection keyed by iso3) for the choropleth
GET  /api/data/catalog         → DataCatalogEntry[]          as_of, retrieved, license, confidence, fetch_status, freshness, stale_reason
GET  /api/data/countries       → {snapshot_id, countries: CountrySummary[]}
GET  /api/data/countries/{iso3}[?series=1] → CountryProfile  every value {…, source, as_of, confidence, license, retrieved}; `missing[]`
GET  /api/data/companies       → {snapshot_id, companies: CompanySummary[]}
GET  /api/data/companies/{ref} → CompanyProfile              ref = id | QID | LEI | ticker | unique id prefix; `missing[]`
                               data routes: 404 unknown, 400 malformed, 503 before the first snapshot
```

Branches: `POST /api/runs` with `parent_run_id` copies the parent's spec and seed, adds interventions parsed from the prompt (or `interventions`), and fixes edited assumptions (`assumptions: {id: value}`). PDF export is the report page printed by the browser (print stylesheet).

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
2. **Done.** FastAPI service; LLM scenario parser with JSON-schema outputs; persona generator from real distributions; product-launch module; persona cognition with a budget manager; summary report. See "M2–M5 as built" and `docs/DEMO-M2.md`.
3. **Done.** Epidemiology, earthquake and trade modules; travel and trade networks; ensembles with 50/90% bands; sensitivity and counterfactuals. `docs/DEMO-M3.md`.
4. **Done.** Branching, compare view, run history, live feeds (USGS, WHO DON), generic fallback module, Markdown and print-to-PDF export, read-only share links. `docs/DEMO-M4.md`.
5. **Done.** Backtests (earthquakes), golden-run regression, contract tests, accessibility and performance checks, Docker/CI, docs. `docs/DEMO-M5.md`.

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

### M2–M5 as built

**Engine pipeline.** `parse → world snapshot → personas → module priors (+ user edits) → ensemble of N runs (default 24, `WORLDSIM_ENSEMBLE`) → the member closest to the median key outcome is re-run with detail and animated → frames → one-at-a-time sensitivity (top 5) and counterfactuals → summary and report`. Every random draw comes from `numpy.random.default_rng([seed, member, …])`, so `(seed, spec, overrides, snapshot)` replays a run exactly; `tests/test_golden.py` pins five reference runs.

**Personas.** Each country's World Bank population is split between Natural Earth cities (scaled so cities never exceed urban population) and a "rest of country" location, then into five segments: children 0–14, adults 65+ (WDI age shares) and working-age adults by income quantile (bottom 50%, middle 40%, top 10%) of a lognormal fitted to GDP per capita and the Gini index. Totals match WDI exactly (`test_personas.py`). About 7,300 people personas plus 8–12 institutions per run. Traits come from data where it exists (internet use, mobile subscriptions, income); institutional trust is a labeled neutral prior until survey data is ingested.

**Modules.** All share `Module.priors()` (every parameter with a central value, a range, origin and source) and `simulate(ctx, params, rng, detail)`.

| Module | Mechanism | Data it uses | Key outcome |
|---|---|---|---|
| launch | Bass diffusion per segment × awareness × availability waves (income group, EU/China review delays) × affordability (income lognormal vs price), supply ramp and backlog, competitor price cut, supplier revenue (BOM shares) | GDP per capita, Gini, internet use, income group, SEC EDGAR revenue for supplier shares | units shipped |
| epidemiology | stochastic age-structured SEIRD on every location; within-country gravity mixing; international seeding through a gravity travel network; hospital surge capacity from beds per 1,000; behavior drop with visible deaths; interventions; ascertainment and reporting lag | population, age shares, hospital beds, physicians, income group | deaths |
| disaster | earthquake intensity (simplified isoseismal relation + finite rupture), PAGER-style fatality curve with θ from GDP per capita, displacement, outages, aftershock (Båth's law), relief capacity | population (cities as discs, rural population over admin-1 areas), GDP per capita | deaths |
| trade | gravity bilateral flows × product share, pass-through, import elasticity, diversion, retaliation, tariff revenue | GDP, distance | lost imports |
| generic | stock-and-flow impact from the origin with hub spillovers, attention and recovery; parameters from the event class and the analog library; always low confidence | population | people materially affected |

**Persona cognition.** Bubbles are templates filled with the persona's own numbers by default. With `WORLDSIM_LLM=on`, up to 8 routine reactions per step go to Claude Haiku 5.5 and up to 4 institutional voices to Claude Sonnet 5.5 (Opus before M6) as JSON-schema calls; a line is accepted only if every number in it appears in its input (`voices.numbers_ok`), otherwise the template is used. `llm.Budget` caps calls per step, per run and in dollars; responses are cached on disk by prompt hash. The parser and the report headline use the same validated path. Prompts live in `worldsim/prompts/` with a version header.

**Uncertainty.** Summary metrics are medians with 5th–95th and 25th–75th percentiles across the ensemble; the timeline draws the band per step. Confidence per output is one rule (`engine.confidence`): low without data, in generic mode, or when more than 12 low-confidence priors drive the run.

**Calibration.** `tests/test_backtests.py` runs six historical earthquakes against the real snapshot: geometric-mean bias about 1.25×, five of six within 4×, Gorkha 2015 overpredicted about 30×. The launch and epidemiology modules are not yet backtested: that needs historical-world snapshots (2007 for the iPhone, 2009 for H1N1), which the pipeline does not build yet.

**Performance** (M-series laptop, Chrome, 2026-10-20): 7,312 persona dots at 16× playback, 103 fps average, p95 frame 17 ms; 15,000 synthetic points with continuous pan and zoom, 104 fps average, p95 9 ms, one 479 ms cluster rebuild. First frame of a launch run about 0.6 s, of an outbreak run about 4 s (24-run ensemble of 365 daily steps).

Deviations from the plan, with the reason:

1. **LLM calls are off by default.** No credentials were available while building, and runs should never spend money silently. The deterministic paths are complete; LLM paths are exercised with a fake client in `tests/test_llm.py`.
2. **No deck.gl.** MapLibre clustering and line layers meet the 60 fps target at 15,000 points (measured above), so the second rendering stack was not needed.
3. **No input-output macro model or bilateral customs data.** Trade uses a gravity baseline and product-share priors until UN Comtrade is ingested; supply-chain prompts use the trade module.
4. **Disaster covers earthquakes.** Floods, cyclones and wildfires run in the generic fallback until their hazard models and exposure data exist.
5. **Branching re-runs from day 0** with the parent's seed and the new interventions at their day, rather than resuming saved mid-run state; `branch_at` records where the user asked.
6. **Feeds:** USGS and WHO Disease Outbreak News are wired with cache and stale flags. GDELT and market prices are not: GDELT's API is unstable for unattended use and market data needs a licensed provider.
7. **Run storage** is JSON configs on disk (`services/sim/runs/`) plus an in-memory cache of recent runs; frames are recomputed from the config on replay.

### M6 as built: agents layer and scale

**Rules.** Agents make categorical choices and place values inside code-defined ranges; Python clamps (JSON schemas cannot enforce min/max) and rejects proposals that cite evidence ids no tool returned. Every decision is written into the `ScenarioSpec` (`assumptions` with origin `llm`, `policies`, `behavior`, `scale`, `plausibility`), so `(seed, spec, snapshot)` still replays a run exactly and branches inherit decisions. Agent prose (report paragraphs, critic flags, voice lines) is stored in the run file's `agents` block, so a replay makes no API call. `runs/<id>.agents.jsonl` audits every call but is never needed for replay. With the LLM off, every role keeps its rule-based path and the golden runs are unchanged.

**Roles** (`worldsim/agents.py`, prompts `worldsim/prompts/agent_*.md`; a dict of roles and plain functions, no orchestrator):

| Role | Model | When | Writes |
|---|---|---|---|
| Intake | Opus 5.5, low | `POST /runs` | event fields, plausibility verdict (impossible → clarifying question) |
| Calibrator | Sonnet 5.5, medium | setup, parallel | origin-`llm` assumptions that narrow module priors |
| Actors | Sonnet 5.5, medium | setup, parallel, when the module has a policy menu | `spec.policies` + their prior centers |
| Crowds | Haiku 5.5, low | setup, parallel, when the module has behavior dimensions | `spec.behavior` stances |
| Scale assessor | Opus 5.5, medium | background after setup | `spec.scale`: reach forecast, analog bands, escalation paths as prior tails |
| Actors, re-plan | Sonnet 5.5, low | after a first look at 8 paired runs | revised `spec.policies`; first plan kept for the adaptation effect |
| Reporter, critic | Opus 5.5, Sonnet 5.5 | `finish()`, in parallel | headline and scale paragraphs; judgment flags |

`llm.agent` is a manual tool-use loop: strict read-only tools from `worldsim/evidence.py` (gazetteer, country profiles, indicator series, companies, analogs, priors), the final answer as a JSON schema in the same request, `tool_choice` auto with `none` on the last turn, top-level prompt caching, and sub-budgets that also charge the run budget ($1.00 and 80 calls by default; voices get $0.18 and 60 calls of it).

**Scale** (`worldsim/scale.py`, deterministic). Each module sets `Trajectory.affected_loc` (people materially affected per location). Reach class per ensemble member: local, regional, national (≥25% of the country), multi-country, global (≥25 countries on ≥3 continents), each needing at least 100 people and 0.01% of a country. Magnitude: the headline outcome against same-module analogs in bands (far below <0.1×, below, comparable within 3×, above, far above >10×). Escalation paths: priors pushed into their tails (or all policies disabled), re-run on the base members' seeds, with the count of base runs that reach the path's median. The assessor's forecast is scored against all of this, and each streamed run appends forecast and measurement to `runs/calibration.jsonl`.

**Actor policies** (`modules/base.py`). A module's `policy_menu` lists actions with a trigger metric and ranges for threshold, lag and duration (epidemiology: stay-at-home order, border closure, vaccine program; disaster: relief deployment; trade: retaliatory tariffs). Each policy's numbers are priors `pol_<id>_*`, so the ensemble samples them and sensitivity ranks them; `fire_policies` is RNG-free and fires per country for country metrics, so a detail run still equals its member.

**Crowd behavior.** A module's `behavior_dims` (epidemiology: contact reduction, compliance; launch: adoption willingness) take stance labels per cluster (origin country, World Bank income groups). Code maps each label to a multiplier band and makes it a prior `beh_<cluster>_<dim>`, appended after the module's priors so earlier draws are unchanged.

**Evaluation.** `evals/scale_cases.jsonl` phrases eleven historical events as prompts; `tests/test_scale_eval.py` scores reach class and magnitude band against the analog library on the real snapshot (2026-11-23: reach 7 of 11, within 10× in 7 of 10) and fails below floors of 7 and 5. Origins and epicenters come from `apps/web/data/places.json` (Natural Earth 1:50m, which also places personas) and then a lookup-only gazetteer, `apps/web/data/gazetteer.json` (Natural Earth 1:10m, population ≥ 50,000; `apps/web/scripts/fetch-gazetteer.mjs`), matched only as capitalized in the prompt.

**Concurrency.** `Budget.allow` reserves a call before it is made, so the eight concurrent voice workers cannot overshoot a call cap. Every stream of a run holds `Run.lock` while it runs the pipeline, so a second stream or a report request waits and then replays; `api.get_run` hands concurrent first requests the same `Run`.

Not built: per-persona LLM agents, per-step LLM decisions inside a run, an LLM orchestrator, fine-tuning. Actors do not yet replace the hard-coded institution personas, and disaster, trade and generic have no crowd dimensions.

## 10. Open decisions

None blocking. Revisit at M1: hosting (Vercel for web and light API; the sim service on a container host), graph store (Postgres CTEs vs Neo4j), LLM provider via a gateway.
