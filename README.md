# Worldsim

A prompt-driven world event simulator. Type an event, watch it unfold on a monochrome world map with personas who speak, and get a written summary when the run finishes.

Everything on screen is a **simulation**, not a forecast or advice. Simulated today is **2026-10-20**.

**Status: Milestone 1.** A deterministic **mock engine** streams over the real API contract (M0), and a real data layer (M1) serves countries and ~500 companies from World Bank, Natural Earth, Wikidata, GLEIF and SEC EDGAR, every value with provenance. The engine starts reading that data in Milestone 2. See `docs/ARCHITECTURE.md`.

## Run

```bash
cd data && uv venv --python 3.13 .venv && uv pip install --python .venv/bin/python -r requirements.txt
cd data && .venv/bin/python -m pipeline run      # build data/snapshots/<today>/ from live sources (cache fallback)
cd apps/web && npm install && npm run dev
```

Open http://localhost:3000. Needs internet for basemap tiles (OpenFreeMap). **Data** in the top bar (or `/sources`) shows every dataset with its freshness.

```bash
cd data && .venv/bin/python -m pytest pipeline/tests -q   # loader + per-source data-contract tests
cd data && .venv/bin/python -m pipeline status           # freshness of the latest snapshot (exit 1 if stale)
cd apps/web && npm test          # unit tests (vitest)
cd apps/web && npm run build     # production build, includes typecheck + lint
node apps/web/scripts/fetch-places.mjs   # regenerate data/places.json from Natural Earth
```

## Layout

```
apps/web        Next.js 16 · TypeScript · Tailwind v4 · MapLibre GL · DuckDB (read API over the data snapshot)
data/pipeline   Python 3.13 ETL: one job per source → schema-validated Parquet snapshot in data/snapshots/
docs/           ARCHITECTURE.md (data model, module interfaces, API contract, milestones)
                DESIGN.md (tokens, map palette, status encoding, accessibility)
                DEMO-M0.md, DEMO-M1.md (demo scripts)
```

## Milestones

| # | Scope | Status |
|---|---|---|
| 0 | Scaffold, design system, basemap, layout, mock data end to end | done |
| 1 | Data layer v1: countries + ~500 companies with provenance | done |
| 2 | FastAPI sim service, LLM parser, product-launch module, personas, summary report | |
| 3 | Epidemiology, disaster, macro/supply-chain modules, networks, ensembles | |
| 4 | Branching, compare view, real-time feeds, generic fallback, export, sharing | |
| 5 | Calibration, backtests, performance, accessibility, docs | |
