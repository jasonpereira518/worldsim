# Worldsim

A prompt-driven world event simulator. Type an event, watch it unfold on a monochrome world map with personas who speak, and get a written report with ranges when the run finishes.

Everything on screen is a **simulation**, not a forecast or advice. Simulated today is **2026-10-20**.

**Status: Milestones 0–5 built.** A Python simulation service runs domain modules (product launch, epidemiology, earthquake, trade, and a generic fallback) as 24-run ensembles over a real data snapshot (World Bank, Natural Earth, Wikidata, GLEIF, SEC EDGAR). The Next.js app streams the median run, shows the uncertainty band, and produces an 11-section report. See `docs/ARCHITECTURE.md` for the design, what was built, and the deviations from the brief.

## Run

```bash
cd data && uv venv --python 3.13 .venv && uv pip install --python .venv/bin/python -r requirements.txt
```

```bash
cd data && .venv/bin/python -m pipeline run
```

```bash
cd services/sim && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
```

```bash
cd apps/web && npm install && npm run sim
```

```bash
cd apps/web && npm run dev
```

Open http://localhost:3000. Basemap tiles (OpenFreeMap) and live feeds need internet. Without the sim service, the web app falls back to the Milestone 0 mock engine and labels it "Mock engine".

LLM parsing, persona voices and the agents layer are off by default. To enable them, start the service with `WORLDSIM_LLM=on` and Anthropic credentials (`docs/DEMO-M2.md`, step 4). Runs then spend API credit within a per-run cap of $1.00. With agents on, Claude roles calibrate parameters, choose actor policies and crowd stances, forecast the event's scale, and review the report; the engine still computes every number (`docs/DEMO-M6.md`). The Scale card (reach, magnitude against past events, escalation paths) works with the LLM off.

Docker alternative:

```bash
docker compose run --rm pipeline
```

```bash
docker compose up --build sim web
```

## Tests

```bash
cd data && .venv/bin/python -m pytest pipeline/tests -q
```

```bash
cd services/sim && .venv/bin/python -m pytest -q
```

```bash
cd apps/web && npm run lint && npm test && npm run build
```

## Layout

```
apps/web        Next.js 16 · TypeScript · Tailwind v4 · MapLibre GL · DuckDB read API; proxies /api/runs/* to the sim service
services/sim    Python 3.13 FastAPI: personas, modules, ensembles, voices, reports, chat, compare, live feeds
data/pipeline   Python ETL: one job per source → schema-validated Parquet snapshot in data/snapshots/
docs/           ARCHITECTURE.md, DESIGN.md, DEMO-M0.md … DEMO-M5.md
```

## Milestones

| # | Scope | Status | Demo |
|---|---|---|---|
| 0 | Scaffold, design system, basemap, layout, mock data end to end | done | `docs/DEMO-M0.md` |
| 1 | Data layer v1: countries + ~500 companies with provenance | done | `docs/DEMO-M1.md` |
| 2 | Sim service, parser, personas from real distributions, launch module, voices, report | done | `docs/DEMO-M2.md` |
| 3 | Epidemiology, earthquake, trade modules; networks; ensembles, sensitivity, counterfactuals | done | `docs/DEMO-M3.md` |
| 4 | Branching, compare, run history, live feeds, generic fallback, export, sharing | done | `docs/DEMO-M4.md` |
| 5 | Backtests, golden runs, contract tests, performance, accessibility, Docker, CI | done | `docs/DEMO-M5.md` |
