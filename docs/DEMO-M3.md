# Demo script — Milestone 3 (epidemiology, earthquake, trade, ensembles)

About ten minutes, with both servers running (`docs/DEMO-M2.md`, step 1).

## 1. Walkthrough B: outbreak

Click **A novel H5N1 variant begins human-to-human transmission in Vietnam**.

- The progress label reads "Running ensemble N of 24" for about four seconds, then frames stream.
- Infections are seeded in a rural cluster, the part of Vietnam's population outside listed cities. Spread follows within-country gravity mixing and a travel network, and the moments list "Community transmission in …" in arrival order.
- **Map layer:** reported cases per 100k, deaths per 100k, hospital demand against surge beds (from World Bank hospital beds per 1,000), and the drop in contacts.
- Bubbles from the Ministry of Health, WHO, CDC, ECDC, Lufthansa and vaccine makers change as detection, reporting and hospital load cross their thresholds.
- The band is wide on purpose. R0 (1.4–2.8) and severity (0.2–5×) for a pathogen without human-transmission history dominate the uncertainty, and section 8 of the report ranks them.
- Section 9 of the report gives counterfactual runs: borders closed on day 10, a lockdown in the origin country on day 14, and a vaccine 80 days sooner.

## 2. Earthquake

Type **A magnitude 8.1 quake hits Istanbul**.

- The shaking layer (MMI) and the deaths, displacement and outage layers fill in over the first days. Deaths converge as reports arrive, an aftershock follows Båth's law, and displacement peaks on day 3.
- The report's calibration note gives the backtest result on six historical earthquakes.

## 3. Walkthrough C: tariff

Type **The EU imposes a 40% tariff on Chinese EVs**.

- The importer resolves to the 27 EU members and the exporter to China, with electric vehicles as the product. Flows run from China into EU hubs, plus diversion arcs from other suppliers.
- Outcomes: lost imports, the consumer price change (tariff × pass-through), diversion, tariff revenue, and the share of runs with retaliation.

## 4. Generic fallback

Type **Mass protests erupt in Lagos over fuel prices**. The badge and report read low confidence, and the report names the closest analogs from the event library.

## 5. Checks

```bash
cd services/sim && .venv/bin/python -m pytest -q tests/test_modules.py tests/test_backtests.py
```
