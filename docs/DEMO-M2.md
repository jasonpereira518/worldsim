# Demo script — Milestone 2 (simulation service, product launch)

About ten minutes. Needs a data snapshot (`docs/DEMO-M1.md`, step 1) and internet for basemap tiles.

## 1. Start both servers

```bash
cd services/sim && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
```

```bash
cd apps/web && npm run sim
```

```bash
cd apps/web && npm run dev
```

Open http://localhost:3000. The badge in the top bar reads "Simulation" until a run starts. `curl http://127.0.0.1:8731/health` reports the snapshot id, `llm: off` and the ensemble size.

## 2. Walkthrough A: product launch

Click **Apple launches a $499 AR headset worldwide on Dec 1, 2026**.

- **Interpretation card:** launch module, origin at Apple's headquarters from the company store, launch date 2026-12-01 (the run starts six weeks earlier, at t0, to simulate the announcement window), price $499. Chips show origin (`user`, `data`, `model`) and confidence on hover.
- **Map:** persona dots move from hollow (unaware) to gray (aware, considering) to black (adopted). Gray-filled rings mark segments priced out of the device. Squares are institutions: Apple, Meta, Samsung, Sony, TSMC, Foxconn and its Zhengzhou plant, a Best Buy store in Ohio, the European Commission and China's market regulator.
- **Bubbles** quote the persona's own numbers. Hover one for "Why": the state change and the metric before and after.
- **Timeline band:** the light band is the 90% interval of units shipped across 24 runs, the dark band is the 50% interval, and the line is the median. The map shows the median run.
- **Notable moments:** pre-orders open, launch in high-income markets, the EU and China after their review delays, later waves, and a competitor price cut once units cross its trigger.
- **Map layer** (top left) shades countries by adopters per 1,000 people, units shipped, or on-sale status.

At the end of the timeline the **Summary** card lists medians with 90% intervals. **Full report** opens the 11-section report. Section 5 cites each supplier's added revenue as a share of its SEC EDGAR revenue where the store has it.

## 3. Assumptions you can change

Click **Show model assumptions** on the interpretation card. Every numeric prior is a chip with its range and source (for example the Bass coefficients cite Sultan, Farley & Lehmann 1990). Click one, type a new value and press Enter. The run branches with the same seed, so the difference comes from your edit.

## 4. Persona cognition with an LLM (optional, spends API credit)

```bash
cd services/sim && WORLDSIM_LLM=on ANTHROPIC_API_KEY=... .venv/bin/python -m uvicorn worldsim.api:app --port 8731
```

The parser, up to 8 routine reactions per step (Claude Haiku 5.5), up to 4 institutional voices (Claude Opus 5.5) and the report headline then use the LLM. A line is kept only when every number in it appears in its input. The budget caps default to 60 calls and $0.50 per run (`WORLDSIM_LLM_MAX_CALLS`, `WORLDSIM_LLM_MAX_USD`), and usage appears in the report's confidence section.

## 5. Checks

```bash
cd services/sim && .venv/bin/python -m pytest -q
```
