"""Summary report (spec section 8): built from run artifacts, rendered to JSON and Markdown."""
from __future__ import annotations

import datetime as dt

import numpy as np

from . import llm
from .util import add_days, fmt
from .analogs import analogs_for
from .voices import numbers_ok

DISCLAIMER = 'Simulation output, not a forecast or advice. Every number traces to a dataset or a labeled assumption listed in the appendix.'


def _companies_pct(run, company_role: str, usd_b: float):
    inst = next((i for i in run.ctx.institutions if i.role == company_role and i.company_id), None)
    if not inst:
        return None, None
    c = run.ctx.world.companies.get(inst.company_id)
    rev = c.financials.get('revenue') if c else None
    if rev and rev.value > 0:
        return c.name, f'{usd_b * 1e9 / rev.value * 100:.2f}% of FY{rev.year} revenue ({rev.source})'
    return (c.name if c else inst.label), 'revenue base not in the company store'


def winners_losers(run) -> dict:
    tr, mod = run.traj, run.module.name
    med = {k: np.median([e.outcomes.get(k, np.nan) for e in run.ensemble]) for k in run.traj.outcomes}
    win, lose = [], []
    if mod == 'launch':
        maker = next((i for i in run.ctx.institutions if i.role == 'maker'), None)
        if maker:
            name, pct = _companies_pct(run, 'maker', med['revenue_busd'])
            win.append({'name': maker.label, 'why': f'${med["revenue_busd"]:.1f}B device revenue (median)', 'detail': pct})
        for role, key in (('assembler', 'assembler_revenue_busd'), ('foundry', 'foundry_revenue_busd')):
            name, pct = _companies_pct(run, role, med[key])
            if name:
                win.append({'name': name, 'why': f'+${med[key]:.2f}B from the program (BOM share prior)', 'detail': pct})
        if np.isfinite(med.get('competitor_cut_week', np.nan)):
            for c in [i for i in run.ctx.institutions if i.role == 'competitor'][:1]:
                lose.append({'name': c.label, 'why': f'forced price cut around week {med["competitor_cut_week"]:.0f}', 'detail': 'competitor response prior'})
        for row in tr.breakdown.get('priced_out', [])[:3]:
            lose.append({'name': f'Buyers in {row["country"]}', 'why': f'{row["people_m"]}M people priced out at this price', 'detail': 'income distribution model'})
    else:
        win += tr.breakdown.get('winners', [])
        lose += tr.breakdown.get('losers', [])
    return {'winners': win, 'losers': lose}


def pick_voices(run, n: int = 8) -> list[dict]:
    seen_c, seen_s, out = set(), {}, []
    allb = sorted((b for f in run.frames for b in f.bubbles), key=lambda b: -b.priority)
    byid = {p.id: p for p in run.personas}
    for b in allb:
        p = byid[b.persona_id]
        c, s = p.location['country_iso3'], b.why.event.split(' → ')[-1]
        if c in seen_c or seen_s.get(s, 0) >= 2:
            continue
        seen_c.add(c)
        seen_s[s] = seen_s.get(s, 0) + 1
        out.append({'quote': b.text, 'persona': p.label, 'kind': p.kind, 'date': run.frames[b.t].date,
                    'data': f'{b.why.event}; {b.why.metric} {b.why.before:g} → {b.why.after:g} {b.why.unit}', 'generator': b.generator})
        if len(out) >= n:
            break
    return out


def timeline(run, lo: int = 8, hi: int = 15) -> list[dict]:
    ev = [e for f in run.frames for e in f.events]
    pick = [e for e in ev if e.severity == 3]
    rest = [e for e in ev if e.severity == 2] + [e for e in ev if e.severity == 1]
    while len(pick) < lo and rest:
        pick.append(rest.pop(0))
    pick = sorted(pick, key=lambda e: e.t)[:hi]
    return [{'date': e.date, 'day': e.t * run.ctx.dt, 'title': e.title, 'cause': e.cause, 'places': e.places} for e in pick]


def geography(run) -> dict:
    tr = run.traj
    tables = {k: v for k, v in tr.breakdown.items() if k not in ('winners', 'losers')}
    last = tr.layers[-1] if tr.layers else {}
    first_layer = run.module.layers[0][0] if run.module.layers else None
    # rank countries with at least 1M people: per-capita layers in microstates are noisy and rarely the story
    ok = {c for c in run.ctx.iso3 if run.ctx.c_pop[run.ctx.c_idx[c]] >= 1e6}
    top = sorted(((k, v) for k, v in last.get(first_layer, {}).items() if k in ok), key=lambda kv: -abs(kv[1]))[:10] if first_layer else []
    return {'tables': tables, 'top_by_layer': [{'iso3': k, 'country': run.ctx.c_name[run.ctx.c_idx[k]] if k in run.ctx.c_idx else k, 'value': v} for k, v in top],
            'layer': {'key': first_layer, 'label': run.module.layers[0][1], 'unit': run.module.layers[0][2]} if first_layer else None,
            'final_layers': last}


def confidence_section(run) -> dict:
    lows = [p for p in run.priors if p.confidence == 'low' and p.high > p.low]
    stale = [c for c in run.ctx.world.catalog if c.get('fetch_status') in ('cached', 'partial', 'unavailable')]
    gaps = [a.text for a in run.ctx.pop.assumptions if a.confidence == 'low']
    from .engine import confidence
    overall = confidence(run)
    reasons = [f'{run.module.name} module confidence: {run.module.confidence}', f'{len(lows)} low-confidence priors carry ranges into the ensemble']
    if run.module.name == 'generic':
        reasons.append('generic fallback mode: mechanisms and parameters come from the closest analog class, not a domain model')
    if not run.ctx.world.available:
        reasons.append('no data snapshot: indicators unavailable')
    return {'overall': overall, 'reasons': reasons, 'data_gaps': gaps,
            'stale_sources': [f'{c["name"]} ({c["fetch_status"]}, as of {c["as_of"]})' for c in stale],
            'calibration': getattr(run.module, 'calibration_note', 'Not yet backtested against historical analogs.'),
            'analogs': analogs_for(run.config.spec),
            'llm_usage': run.budget.report()}


def appendix(run) -> dict:
    spec = run.config.spec
    datasets = list(run.ctx.world.catalog) + [
        {'id': 'ne_places', 'name': 'Natural Earth populated places 1:50m', 'source': 'Natural Earth v5.1.1', 'as_of': '2022-05-13', 'license': 'Public domain', 'confidence': 'medium'},
        {'id': 'basemap', 'name': 'OpenFreeMap vector tiles (OpenMapTiles schema)', 'source': '© OpenStreetMap contributors', 'as_of': None, 'license': 'ODbL', 'confidence': 'high'},
    ]
    assumptions = [a.model_dump() for a in spec.assumptions] + [p.assumption(p.key in run.overrides).model_dump() for p in run.priors] + \
                  [a.model_dump() for a in run.ctx.pop.assumptions]
    return {'datasets': datasets, 'assumptions': assumptions,
            'run': {'run_id': run.config.run_id, 'seed': run.config.seed, 'engine': run.config.engine_version, 'snapshot': run.config.data_snapshot,
                    'ensemble_size': len(run.ensemble), 'median_member': run.median, 'parser': spec.parser, 'parent_run_id': run.config.parent_run_id,
                    'branch_at': run.config.branch_at, 'timings_s': {k: round(v, 2) for k, v in run.timings.items()}}}


def decision_points(run) -> list[dict]:
    key_unit = run.module.key_unit
    out = []
    for cf in run.counterfactuals:
        out.append({'action': cf['action'], 'trigger': cf['trigger'],
                    'effect': f'{cf["change_pct"]:+.0f}% {key_unit} vs the central run ({fmt(cf["baseline"])} → {fmt(cf["outcome"])})', 'basis': 'counterfactual run'})
    for s in run.sensitivity[:3]:
        better = 'high' if s['outcome_high'] > s['outcome_low'] else 'low'
        out.append({'action': f'Watch: {s["text"]}', 'trigger': f'evidence it sits near the {better} end ({s[better]:g} {s["unit"]})',
                    'effect': f'{key_unit} ranges {fmt(s["outcome_low"])}–{fmt(s["outcome_high"])} across its prior', 'basis': 'sensitivity'})
    return out


HEADLINE_SCHEMA = {'type': 'object', 'additionalProperties': False, 'required': ['paragraph'], 'properties': {'paragraph': {'type': 'string'}}}


def headline(run) -> tuple[str, str]:
    s = run.summary
    k = s.metrics[0]
    end = add_days(run.config.spec.start_date, run.ctx.steps * run.ctx.dt)
    lines = [f'{m.name}: {fmt(m.value)} {m.unit} (90% interval {fmt(m.low)}–{fmt(m.high)})' for m in s.metrics[:4]]
    text = (f'By {end}, the median simulated {k.name.lower()} is {fmt(k.value)} {k.unit} (90% interval {fmt(k.low)}–{fmt(k.high)}). '
            + ' '.join(f'{l}.' for l in lines[1:3]) + f' Driven by {", ".join(run.module.mechanisms[:3])}. '
            f'{len(run.ensemble)}-run ensemble, {confidence_section(run)["overall"]} confidence; a simulation, not a forecast.')
    if llm.enabled():
        facts = f'Scenario: {run.config.spec.title}\nHorizon end: {end}\nOutcomes:\n' + '\n'.join(lines) + f'\nMechanisms: {", ".join(run.module.mechanisms)}'
        out = llm.structured(llm.prompt('report_headline'), facts, HEADLINE_SCHEMA, budget=run.budget, max_tokens=1500)
        if out and numbers_ok(out['paragraph'], facts):
            return out['paragraph'], 'llm'
    return text, 'template'


def build_report(run) -> dict:
    head, gen = headline(run)
    spec = run.config.spec
    return {
        'run_id': run.config.run_id, 'title': spec.title, 'prompt': spec.prompt, 'event_type': spec.event_type, 'module': run.module.name,
        'generated_at': dt.datetime.now(dt.UTC).isoformat(timespec='seconds'), 'start_date': spec.start_date,
        'end_date': add_days(spec.start_date, run.ctx.steps * run.ctx.dt), 'disclaimer': DISCLAIMER,
        'headline': head, 'headline_generator': gen,
        'key_outcomes': [m.model_dump() for m in run.summary.metrics],
        'timeline': timeline(run), 'geography': geography(run), 'winners_losers': winners_losers(run), 'voices': pick_voices(run),
        'causal': run.traj.causal, 'sensitivities': run.sensitivity, 'decision_points': decision_points(run),
        'confidence': confidence_section(run), 'appendix': appendix(run),
        'series': {'key': run.module.key_metric, 'unit': run.module.key_unit, 'dates': [f.date for f in run.frames],
                   'band': [f.band for f in run.frames]},
    }


def _n(v, unit=''):
    return f'{fmt(v)}' if isinstance(v, (int, float)) else str(v)


def to_markdown(r: dict) -> str:
    L = [f'# {r["title"]}', '', f'> {r["disclaimer"]}', '', f'Prompt: *{r["prompt"]}*  ', f'Horizon: {r["start_date"]} to {r["end_date"]} · module: {r["module"]}', '',
         '## 1. Headline', '', r['headline'], '', '## 2. Key outcomes', '', '| Metric | Median | 50% interval | 90% interval | Unit | Confidence |', '|---|---:|---:|---:|---|---|']
    for m in r['key_outcomes']:
        L.append(f'| {m["name"]} | {_n(m["value"])} | {_n(m["low50"])}–{_n(m["high50"])} | {_n(m["low"])}–{_n(m["high"])} | {m["unit"]} | {m["confidence"]} |')
    L += ['', '## 3. Timeline of key moments', '']
    L += [f'- **{e["date"]}** (day {e["day"]}) {e["title"]}. Cause: {e["cause"]}.' + (f' Places: {", ".join(e["places"])}.' if e['places'] else '') for e in r['timeline']]
    L += ['', '## 4. Geographic breakdown', '']
    g = r['geography']
    if g['layer']:
        L += [f'Top 10 by {g["layer"]["label"].lower()} ({g["layer"]["unit"]}):', '']
        L += [f'{i + 1}. {row["country"]}: {_n(row["value"])}' for i, row in enumerate(g['top_by_layer'])]
    for name, rows in g['tables'].items():
        if rows:
            cols = list(rows[0].keys())
            L += ['', f'**{name.replace("_", " ").capitalize()}**', '', '| ' + ' | '.join(cols) + ' |', '|' + '---|' * len(cols)]
            L += ['| ' + ' | '.join(str(row[c]) for c in cols) + ' |' for row in rows]
    L += ['', '## 5. Winners and losers', '']
    for side in ('winners', 'losers'):
        L += [f'**{side.capitalize()}**', '']
        L += [f'- {w["name"]}: {w["why"]}' + (f' ({w["detail"]})' if w.get('detail') else '') for w in r['winners_losers'][side]] or ['- none identified']
        L.append('')
    L += ['## 6. Voices', '']
    L += [f'> "{v["quote"]}"  \n> {v["persona"]}, {v["date"]}. Data: {v["data"]}.' + '\n' for v in r['voices']]
    L += ['## 7. Causal chain', '']
    nodes = {n['id']: n['label'] for n in r['causal'].get('nodes', [])}
    L += [f'- {nodes.get(e["from"], e["from"])} → {nodes.get(e["to"], e["to"])}' + (f' ({e["label"]})' if e.get('label') else '') for e in r['causal'].get('edges', [])]
    L += ['', '## 8. Sensitivities and risks', '', '| Assumption | Range | Outcome at low | Outcome at high |', '|---|---|---:|---:|']
    L += [f'| {s["text"]} | {s["low"]:g}–{s["high"]:g} {s["unit"]} | {_n(s["outcome_low"])} | {_n(s["outcome_high"])} |' for s in r['sensitivities']]
    L += ['', '## 9. Decision points', '', '*Analysis of what would have changed the simulated outcome, not a recommendation.*', '']
    L += [f'- **{d["action"]}** when {d["trigger"]}: {d["effect"]} ({d["basis"]}).' for d in r['decision_points']]
    c = r['confidence']
    L += ['', '## 10. Confidence and limitations', '', f'Overall: **{c["overall"]}**.', ''] + [f'- {x}' for x in c['reasons']]
    L += [f'- Data gap: {x}' for x in c['data_gaps']] + [f'- Stale source: {x}' for x in c['stale_sources']] + [f'- Calibration: {c["calibration"]}']
    L += [f'- Analog: {a["name"]}: {a["outcomes"]} ({a["source"]})' for a in c.get('analogs', [])]
    L += ['', '## 11. Sources and assumptions', '', '| Dataset | Source | As of | License |', '|---|---|---|---|']
    L += [f'| {d["name"]} | {d["source"]} | {d.get("as_of") or "n/a"} | {d["license"]} |' for d in r['appendix']['datasets']]
    L += ['', '| Assumption | Value | Origin | Confidence | Source |', '|---|---|---|---|---|']
    L += [f'| {a["text"]} | {a["value"] if a["value"] is not None else ""} {a.get("unit") or ""} | {a["origin"]} | {a["confidence"]} | {a.get("source") or ""} |'
          for a in r['appendix']['assumptions']]
    run = r['appendix']['run']
    L += ['', f'Run `{run["run_id"]}` · seed {run["seed"]} · {run["engine"]} · snapshot `{run["snapshot"]}` · ensemble {run["ensemble_size"]} (median member {run["median_member"]}).', '']
    return '\n'.join(L)
