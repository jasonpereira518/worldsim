# Worldsim

A prompt-driven world event simulator. Type an event, watch it unfold on a monochrome world map with personas who speak, and get a written summary when the run finishes.

Everything on screen is a **simulation**, not a forecast or advice. Simulated today is **2026-10-20**.

**Status: Milestone 0.** Repo scaffold, design system, monochrome basemap, layout, and a deterministic **mock engine** streaming over the real API contract. The LLM parser, real data layer, and domain modules arrive in Milestones 1–3. See `docs/ARCHITECTURE.md`.

## Run

```bash
cd apps/web && npm install && npm run dev
```

Open http://localhost:3000. Needs internet for basemap tiles (OpenFreeMap).

```bash
cd apps/web && npm test          # unit tests (vitest)
cd apps/web && npm run build     # production build, includes typecheck + lint
node apps/web/scripts/fetch-places.mjs   # regenerate data/places.json from Natural Earth
```

## Layout

```
apps/web        Next.js 16 · TypeScript · Tailwind v4 · MapLibre GL
docs/           ARCHITECTURE.md (data model, module interfaces, API contract, milestones)
                DESIGN.md (tokens, map palette, status encoding, accessibility)
                DEMO-M0.md (demo script for this milestone)
```

## Milestones

| # | Scope | Status |
|---|---|---|
| 0 | Scaffold, design system, basemap, layout, mock data end to end | done |
| 1 | Data layer v1: countries + ~500 companies with provenance | next |
| 2 | FastAPI sim service, LLM parser, product-launch module, personas, summary report | |
| 3 | Epidemiology, disaster, macro/supply-chain modules, networks, ensembles | |
| 4 | Branching, compare view, real-time feeds, generic fallback, export, sharing | |
| 5 | Calibration, backtests, performance, accessibility, docs | |
