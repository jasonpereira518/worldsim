# Demo script — Milestone 5 (calibration, regression, performance, accessibility, delivery)

About ten minutes.

## 1. Test suites

```bash
cd data && .venv/bin/python -m pytest pipeline/tests -q
```

```bash
cd services/sim && .venv/bin/python -m pytest -q
```

```bash
cd apps/web && npm run lint && npm test && npm run build
```

The sim suite includes:
- `test_contract.py`: the TypeScript and Pydantic contracts agree in both directions.
- `test_golden.py`: five reference runs reproduce exactly from their seed. Regenerate them deliberately with `WORLDSIM_UPDATE_GOLDEN=1`.
- `test_backtests.py`: six historical earthquakes against the real snapshot.
- `test_llm.py`: budget, cache, refusal handling, and rejection of invented numbers.

The web suite includes `a11y.test.ts`, which checks WCAG AA contrast for both themes' tokens.

## 2. Reproducibility

Open any run's report and note the seed and snapshot in the footer. Reload `/?run=<run_id>`: the replay matches frame for frame.

## 3. Performance

With a finished outbreak run at 16× playback, open the browser console and run:

```js
let n = 0, t0 = performance.now(); (function f(){ n++; if (performance.now() - t0 < 3000) requestAnimationFrame(f); else console.log(Math.round(n / 3), 'fps'); })();
```

The figures measured during the build (7,312 dots during playback, and 15,000 synthetic points with continuous panning) are in `docs/ARCHITECTURE.md`, "M2–M5 as built".

## 4. Accessibility

- Everything is reachable by keyboard. Space plays or pauses, ← and → step, Esc closes drawers and the comparison, and Enter on a bubble opens its persona.
- Progress and notable moments are announced through a polite live region.
- With `prefers-reduced-motion`, dot pulses and flow particles stop.
- Shading never relies on hue: states use fill and shape (hollow, gray, solid, ring, square).

## 5. Containers

```bash
docker compose run --rm pipeline
```

```bash
docker compose up --build sim web
```

Then open http://localhost:3000. CI (`.github/workflows/ci.yml`) runs the three suites on every push.
