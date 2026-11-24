"""Summary report (spec section 8): built from run artifacts, rendered to JSON and Markdown."""
from __future__ import annotations

import datetime as dt
import time

import numpy as np

from . import llm
from .util import add_days, fmt
from .analogs import analogs_for
from .voices import numbers_ok

DISCLAIMER = 'Simulation output, not a forecast or advice. Every number traces to a dataset or a labeled assumption listed in the appendix.'
TIER_LABEL = {'user': 'stated', 'government': 'official', 'peer_reviewed': 'peer-reviewed', 'fit': 'fitted', 'partial': 'partly sourced',
              'guess': 'unverified'}  # same words as the web client (types.ts TIER_LABEL)


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
    prior_keys = {p.key for p in run.priors}  # a prior is the effective value; its spec twin (user or agent edit) is not repeated
    assumptions = [a.model_dump() for a in spec.assumptions if a.id not in prior_keys] + \
                  [p.assumption(p.key in run.overrides).model_dump() for p in run.priors] + [a.model_dump() for a in run.ctx.pop.assumptions]
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


def decisions(run) -> dict | None:
    """Who decided what: each actor policy, in how many ensemble runs it fired and when, what it did in the median run,
    and what the one re-plan round changed (median over the same paired members before and after)."""
    pols, crowds = run.config.spec.policies, run.config.spec.behavior
    if not pols and not crowds:
        return None
    items, vals, n = run.module.policy_menu, {p.key: p for p in run.priors}, len(run.ensemble)
    rows = []
    for pol in pols:
        item = items.get(pol.action)
        if not item:
            continue
        days = [min(d['day'] for d in tr.decisions if d['policy'] == pol.id) for tr in run.ensemble if any(d['policy'] == pol.id for d in tr.decisions)]
        thr, lag = vals[f'pol_{pol.id}_threshold'], vals[f'pol_{pol.id}_lag']
        rows.append({'id': pol.id, 'actor': pol.actor_label, 'action': item['label'], 'scope': pol.scope, 'rationale': pol.rationale, 'revised': pol.revised,
                     'trigger': f'{item["metric_label"]} reaches {fmt(thr.value)} {thr.unit}', 'lag_days': lag.value, 'origin': thr.origin,
                     'fired_runs': len(days), 'n': n, 'median_day': float(np.median(days)) if days else None,
                     # a global trigger fires once for the whole scope, so listing every covered country says nothing
                     'median_run': [{'day': d['day'], 'countries': d['countries'][:8] if item.get('level') == 'country' else [],
                                     'n_countries': len(d['countries']) if item.get('level') == 'country' else 0}
                                    for d in run.traj.decisions if d['policy'] == pol.id][:5]})
    out = {'policies': rows, 'adaptation': None,
           'crowds': [{'label': st.label, 'stances': {d.replace('_', ' '): v for d, v in st.stances.items()}, 'rationale': st.rationale}
                      for st in crowds]}
    rp = run.agent_state.get('replan')
    if rp and rp.get('first_look'):
        look, key = rp['first_look'], run.module.outcome_spec[0][0]
        k = min(look['n'], n)
        out['adaptation'] = {'n': k, 'name': look['outcome']['name'], 'unit': look['outcome']['unit'], 'before': look['outcome']['p50'],
                             'after': float(np.nanmedian([tr.outcomes.get(key, np.nan) for tr in run.ensemble[:k]])), 'revised': rp.get('revised', False),
                             'first_plan': rp.get('first_plan', [])}
    return out


HEADLINE_SCHEMA = {'type': 'object', 'additionalProperties': False, 'required': ['paragraph', 'scale_paragraph'],
                   'properties': {'paragraph': {'type': 'string'}, 'scale_paragraph': {'type': 'string'}}}


def facts(run, dec: dict | None) -> str:
    """Everything the reporter and the critic may state, as text: their numbers are checked against it."""
    s, spec = run.summary, run.config.spec
    end = add_days(spec.start_date, run.ctx.steps * run.ctx.dt)
    L = [f'Scenario: {spec.title}', f'Prompt: {spec.prompt}', f'Horizon end: {end}', f'Ensemble: {len(run.ensemble)} runs', 'Outcomes:']
    L += [f'- {m.name}: {fmt(m.value)} {m.unit} (90% interval {fmt(m.low)}–{fmt(m.high)})' for m in s.metrics[:4]]
    L.append(f'Mechanisms: {", ".join(run.module.mechanisms)}')
    sc = run.scale
    if sc:
        r = sc['measurement']['reach']
        L.append('Reach across runs: ' + ', '.join(f'{REACH_LABEL[c]} {v * 100:.0f}%' for c, v in r['distribution'].items() if v > 0))
        L.append(f'Plausibility: {sc["plausibility"]["verdict"]}' if sc.get('plausibility') else 'Plausibility: not assessed')
        L += [f'- vs {m["name"]}: historical {fmt(m["value"])} {m["metric_name"].lower()}, simulated median {fmt(m["sim"]["p50"])}, {m["band"]}'
              for m in sc['measurement']['magnitude']]
        L += [f'- path "{b["title"]}": median {fmt(b["size"]["p50"])}; {b["exceedance"]["k"]} of {b["exceedance"]["n"]} base runs reach it'
              + (f'; assessor said {b["likelihood"]}' if b.get('likelihood') else '') for b in sc['branches'] if b.get('size') and b.get('exceedance')]
    for p in (dec or {}).get('policies', []):
        L.append(f'- policy: {p["actor"]}, {p["action"]} when {p["trigger"]}; fired in {p["fired_runs"]} of {p["n"]} runs')
    for c in (dec or {}).get('crowds', []):
        L.append(f'- crowd: {c["label"]}: ' + '; '.join(f'{k}: {v}' for k, v in c['stances'].items()))
    L += [f'- sensitivity: {r["text"]}: {fmt(r["outcome_low"])} to {fmt(r["outcome_high"])}' for r in run.sensitivity[:3]]
    return '\n'.join(L)


def reporter(run, text: str) -> tuple[str, str, str | None]:
    """Headline paragraph and scale narrative (LLM), each kept only if every number in it is in the facts."""
    s = run.summary
    k = s.metrics[0]
    end = add_days(run.config.spec.start_date, run.ctx.steps * run.ctx.dt)
    lines = [f'{m.name}: {fmt(m.value)} {m.unit} (90% interval {fmt(m.low)}–{fmt(m.high)})' for m in s.metrics[:4]]
    head = (f'By {end}, the median simulated {k.name.lower()} is {fmt(k.value)} {k.unit} (90% interval {fmt(k.low)}–{fmt(k.high)}). '
            + ' '.join(f'{l}.' for l in lines[1:3]) + f' Driven by {", ".join(run.module.mechanisms[:3])}. '
            f'{len(run.ensemble)}-run ensemble, {confidence_section(run)["overall"]} confidence; a simulation, not a forecast.')
    if llm.enabled():
        b, t0 = run.budget.child(run.budget.max_usd), time.perf_counter()
        out = llm.structured(llm.prompt('report_headline'), text, HEADLINE_SCHEMA, budget=b, max_tokens=2000)
        r = b.report()
        run.audit.append({'role': 'reporter', 'model': llm.MAIN_MODEL, 'ok': out is not None, 'usd': r['usd'], 'calls': r['calls'],
                          'cache_hits': r['cache_hits'], 'refusals': r['refusals'], 'errors': r['errors'],
                          'seconds': round(time.perf_counter() - t0, 2), 'evidence': [], 'output': out})
        if out:
            narrative = out['scale_paragraph'] if out.get('scale_paragraph') and numbers_ok(out['scale_paragraph'], text) else None
            if numbers_ok(out['paragraph'], text):
                return out['paragraph'], 'llm', narrative
            return head, 'template', narrative
    return head, 'template', None


def rule_flags(run, dec: dict | None) -> list[dict]:
    """Deterministic checks of the agents' choices against what the engine measured."""
    out = [{'kind': 'policy_never_fired', 'text': f'{p["actor"]}: {p["action"]} never fired in {p["n"]} runs ({p["trigger"]} was not reached).',
            'generator': 'rules'} for p in (dec or {}).get('policies', []) if p['fired_runs'] == 0]
    sc = run.scale or {}
    for b in sc.get('branches', []):
        if b.get('likelihood') == 'likely' and b.get('computed_likelihood') == 'unlikely':
            ex = b['exceedance']
            out.append({'kind': 'likely_branch_never_reached', 'generator': 'rules',
                        'text': f'The scale assessor judged "{b["title"]}" likely, but only {ex["k"]} of {ex["n"]} base runs reach that size.'})
    m = sc.get('measurement', {})
    f = m.get('forecast')
    if f and not f['reach_hit']:
        out.append({'kind': 'forecast_missed', 'generator': 'rules',
                    'text': f'The scale assessor expected {REACH_LABEL[f["reach_expected"]]} reach; most runs were {REACH_LABEL[m["reach"]["mode"]]}.'})
    mags = [x for x in m.get('magnitude', []) if x['metric'] == m.get('headline_metric')]
    if mags and all(x['band'] in ('far below', 'far above') for x in mags):
        out.append({'kind': 'outside_analog_range', 'generator': 'rules',
                    'text': 'The simulated outcome is more than ten times away from every comparable past event in the library.'})
    return out


def build_report(run) -> dict:
    from concurrent.futures import ThreadPoolExecutor
    from . import agents
    spec, dec = run.config.spec, decisions(run)
    stored = run.agent_state.get('report_text')  # agent prose from the first finish, so a replay makes no calls
    if stored is None:
        text = facts(run, dec)
        with ThreadPoolExecutor(2) as ex:  # reporter and critic in parallel
            rep, crit = ex.submit(reporter, run, text), ex.submit(agents.critic, run, text, run.budget, run.audit)
            head, gen, narrative = rep.result()
            stored = {'headline': head, 'headline_generator': gen, 'scale_narrative': narrative, 'flags': crit.result()}
        if llm.enabled():
            run.agent_state['report_text'] = stored
    conf = confidence_section(run)
    conf['flags'] = rule_flags(run, dec) + stored['flags']
    head, gen = stored['headline'], stored['headline_generator']
    return {
        'run_id': run.config.run_id, 'title': spec.title, 'prompt': spec.prompt, 'event_type': spec.event_type, 'module': run.module.name,
        'generated_at': dt.datetime.now(dt.UTC).isoformat(timespec='seconds'), 'start_date': spec.start_date,
        'end_date': add_days(spec.start_date, run.ctx.steps * run.ctx.dt), 'disclaimer': DISCLAIMER,
        'headline': head, 'headline_generator': gen,
        'key_outcomes': [m.model_dump() for m in run.summary.metrics],
        'timeline': timeline(run), 'geography': geography(run), 'winners_losers': winners_losers(run), 'voices': pick_voices(run),
        'causal': run.traj.causal, 'sensitivities': run.sensitivity, 'decision_points': decision_points(run),
        'confidence': conf, 'appendix': appendix(run), 'decisions': dec,
        'scale': {**run.scale, 'narrative': stored['scale_narrative']} if run.scale else None,
        'series': {'key': run.module.key_metric, 'unit': run.module.key_unit, 'dates': [f.date for f in run.frames],
                   'band': [f.band for f in run.frames]},
    }


def _n(v, unit=''):
    return f'{fmt(v)}' if isinstance(v, (int, float)) else str(v)


REACH_LABEL = {'local': 'local', 'regional': 'regional', 'national': 'national', 'multi_country': 'multi-country', 'global': 'global'}


def scale_markdown(s: dict | None) -> list[str]:
    L = ['## 2. Scale and plausibility', '']
    if not s:
        return L + ['Not assessed for this run.', '']
    if s.get('narrative'):
        L += [s['narrative'], '']
    p = s.get('plausibility')
    if p:
        L += [f'Plausibility: **{p["verdict"]}**' + (f'. {"; ".join(p["reasons"])}' if p.get('reasons') else '') + '.', '']
    r = s['measurement']['reach']
    dist = ', '.join(f'{REACH_LABEL[c]} {v * 100:.0f}%' for c, v in r['distribution'].items() if v > 0)
    n = r.get('countries')
    L += [f'Reach, measured across the ensemble: **{REACH_LABEL[r["mode"]]}** ({dist} of runs)'
          + (f'; countries materially affected: median {n["p50"]:.0f} (90% interval {n["p5"]:.0f}–{n["p95"]:.0f}).' if n else '.')]
    f = s['measurement'].get('forecast')
    if f:
        L += [f'Scale assessor forecast: {REACH_LABEL[f["reach_expected"]]} reach ({"matched" if f["reach_hit"] else "did not match"} the measurement; '
              f'{f["reach_share"] * 100:.0f}% of runs).']
    L += ['', s['measurement']['position'], '']
    rows = s['measurement']['magnitude']
    if rows:
        L += ['| Analog | Metric | Historical | Simulated median (90% interval) | Band | Source |', '|---|---|---:|---:|---|---|']
        L += [f'| {m["name"]} | {m["metric_name"]} | {fmt(m["value"])} | {fmt(m["sim"]["p50"])} ({fmt(m["sim"]["p5"])}–{fmt(m["sim"]["p95"])}) | {m["band"]} | '
              f'{m["source"]}{"; " + m["definition"] if m["definition"] else ""} |' for m in rows]
        L.append('')
    if s.get('branches'):
        L += ['**Escalation paths** (sized by re-running the ensemble with the named assumptions in their tails):', '']
        for b in s['branches']:
            size, ex = b.get('size'), b.get('exceedance')
            line = f'- **{b["title"]}**: {b["path"]}.'
            if size:
                line += f' Headline outcome median {fmt(size["p50"])} (90% interval {fmt(size["p5"])}–{fmt(size["p95"])}).'
            if ex:
                line += f' {ex["k"]} of {ex["n"]} base runs reached {ex["direction"]} that size ({b["computed_likelihood"]})'
                line += f'; the assessor judged it {b["likelihood"]}.' if b.get('likelihood') else '.'
            L.append(line)
        L.append('')
    return L


def decisions_markdown(d: dict | None) -> list[str]:
    if not d:
        return []
    L = ['', '**Who decided what** (actor policies chosen by the actors agent; the engine decides when each fires):', ''] if d['policies'] else []
    for p in d['policies']:
        when = f'fired in {p["fired_runs"]} of {p["n"]} runs' + (f', median day {p["median_day"]:.0f}' if p['median_day'] is not None else '')
        L.append(f'- **{p["actor"]}**: {p["action"]} ({p["scope"].replace("group:", "")}) when {p["trigger"]}, taking effect after {fmt(p["lag_days"])} days; '
                 f'{when}.' + (f' {p["rationale"]}' if p['rationale'] else '') + (' *Revised after the first look.*' if p['revised'] else ''))
    a = d.get('adaptation')
    if a:
        L += ['', f'Re-plan: after a first look at {a["n"]} runs the actors {"revised" if a["revised"] else "kept"} their plan; over those runs the median '
                  f'{a["name"].lower()} went from {fmt(a["before"])} to {fmt(a["after"])} {a["unit"]}.']
    if d.get('crowds'):
        L += ['', '**How populations behave** (crowds agent, relative to the model\'s typical behavior):', '']
        L += [f'- {c["label"]}: ' + '; '.join(f'{k}: {v}' for k, v in c['stances'].items()) + '.' + (f' {c["rationale"]}' if c['rationale'] else '')
              for c in d['crowds']]
    return L


def to_markdown(r: dict) -> str:
    L = [f'# {r["title"]}', '', f'> {r["disclaimer"]}', '', f'Prompt: *{r["prompt"]}*  ', f'Horizon: {r["start_date"]} to {r["end_date"]} · module: {r["module"]}', '',
         '## 1. Headline', '', r['headline'], ''] + scale_markdown(r.get('scale')) + \
        ['## 3. Key outcomes', '', '| Metric | Median | 50% interval | 90% interval | Unit | Confidence |', '|---|---:|---:|---:|---|---|']
    for m in r['key_outcomes']:
        L.append(f'| {m["name"]} | {_n(m["value"])} | {_n(m["low50"])}–{_n(m["high50"])} | {_n(m["low"])}–{_n(m["high"])} | {m["unit"]} | {m["confidence"]} |')
    L += ['', '## 4. Timeline of key moments', '']
    L += [f'- **{e["date"]}** (day {e["day"]}) {e["title"]}. Cause: {e["cause"]}.' + (f' Places: {", ".join(e["places"])}.' if e['places'] else '') for e in r['timeline']]
    L += ['', '## 5. Geographic breakdown', '']
    g = r['geography']
    if g['layer']:
        L += [f'Top 10 by {g["layer"]["label"].lower()} ({g["layer"]["unit"]}):', '']
        L += [f'{i + 1}. {row["country"]}: {_n(row["value"])}' for i, row in enumerate(g['top_by_layer'])]
    for name, rows in g['tables'].items():
        if rows:
            cols = list(rows[0].keys())
            L += ['', f'**{name.replace("_", " ").capitalize()}**', '', '| ' + ' | '.join(cols) + ' |', '|' + '---|' * len(cols)]
            L += ['| ' + ' | '.join(str(row[c]) for c in cols) + ' |' for row in rows]
    L += ['', '## 6. Winners and losers', '']
    for side in ('winners', 'losers'):
        L += [f'**{side.capitalize()}**', '']
        L += [f'- {w["name"]}: {w["why"]}' + (f' ({w["detail"]})' if w.get('detail') else '') for w in r['winners_losers'][side]] or ['- none identified']
        L.append('')
    L += ['## 7. Voices', '']
    L += [f'> "{v["quote"]}"  \n> {v["persona"]}, {v["date"]}. Data: {v["data"]}.' + '\n' for v in r['voices']]
    L += ['## 8. Causal chain', '']
    nodes = {n['id']: n['label'] for n in r['causal'].get('nodes', [])}
    L += [f'- {nodes.get(e["from"], e["from"])} → {nodes.get(e["to"], e["to"])}' + (f' ({e["label"]})' if e.get('label') else '') for e in r['causal'].get('edges', [])]
    L += ['', '## 9. Sensitivities and risks', '', '| Assumption | Range | Outcome at low | Outcome at high |', '|---|---|---:|---:|']
    L += [f'| {s["text"]} | {s["low"]:g}–{s["high"]:g} {s["unit"]} | {_n(s["outcome_low"])} | {_n(s["outcome_high"])} |' for s in r['sensitivities']]
    L += ['', '## 10. Decision points', '', '*Analysis of what would have changed the simulated outcome, not a recommendation.*', '']
    L += [f'- **{d["action"]}** when {d["trigger"]}: {d["effect"]} ({d["basis"]}).' for d in r['decision_points']]
    L += decisions_markdown(r.get('decisions'))
    c = r['confidence']
    L += ['', '## 11. Confidence and limitations', '', f'Overall: **{c["overall"]}**.', ''] + [f'- {x}' for x in c['reasons']]
    L += [f'- Flag ({f["kind"].replace("_", " ")}{", AI critic" if f["generator"] == "llm" else ""}): {f["text"]}' for f in c.get('flags', [])]
    L += [f'- Data gap: {x}' for x in c['data_gaps']] + [f'- Stale source: {x}' for x in c['stale_sources']] + [f'- Calibration: {c["calibration"]}']
    L += [f'- Analog: {a["name"]}: {a["outcomes"]} ({a["source"]})' for a in c.get('analogs', [])]
    L += ['', '## 12. Sources and assumptions', '', '| Dataset | Source | As of | License |', '|---|---|---|---|']
    L += [f'| {d["name"]} | {d["source"]} | {d.get("as_of") or "n/a"} | {d["license"]} |' for d in r['appendix']['datasets']]
    A = r['appendix']['assumptions']
    L += ['', f'{sum(a.get("tier") == "guess" for a in A)} of {len(A)} assumptions are unverified: no official or peer-reviewed source sets '
              'their value, so they enter as ranges (docs/DATA-AUDIT.md).']
    L += ['', '| Assumption | Value | Basis | Origin | Confidence | Source |', '|---|---|---|---|---|---|']
    L += [f'| {a["text"]} | {a["value"] if a["value"] is not None else ""} {a.get("unit") or ""} | {TIER_LABEL.get(a.get("tier"), "unverified")} | '
          f'{a["origin"]} | {a["confidence"]} | {a.get("source") or ""} |' for a in A]
    run = r['appendix']['run']
    L += ['', f'Run `{run["run_id"]}` · seed {run["seed"]} · {run["engine"]} · snapshot `{run["snapshot"]}` · ensemble {run["ensemble_size"]} (median member {run["median_member"]}).', '']
    return '\n'.join(L)
