"""Scale: how small or large a simulated event is, measured from the ensemble. Deterministic; no LLM.

- Reach: each member's people-affected-by-location (Trajectory.affected_loc) → local / regional / national /
  multi-country / global; the distribution across members is the measured reach.
- Magnitude: the headline and other outcomes set beside analogs with the same outcome metric (ratio bands).
- Escalation paths: each path re-runs a small ensemble with chosen priors pushed into a tail, paired with the base
  members (same simulation seeds), so its size and how many base runs reached it are computed, not judged.
An agent's ScaleHypothesis (spec.scale) is a pre-registered forecast; measure() scores it against these numbers.
"""
from __future__ import annotations

import os

import numpy as np

from . import analogs

REACH = ['local', 'regional', 'national', 'multi_country', 'global']
MIN_PEOPLE, MIN_SHARE = 100, 1e-4      # a country is reached when ≥100 people and ≥0.01% of its population are affected
NATIONAL_SHARE = 0.25                  # one country with ≥25% of its people affected → national
GLOBAL_COUNTRIES, GLOBAL_CONTINENTS = 25, 3
BANDS = [(0.1, 'far below'), (1 / 3, 'below'), (3.0, 'comparable'), (10.0, 'above'), (float('inf'), 'far above')]
BRANCH_N = int(os.environ.get('WORLDSIM_BRANCH_ENSEMBLE', 8))


def reach_class(ctx, affected_loc) -> tuple[str, int]:
    """(reach class, countries reached) for one member."""
    if affected_loc is None or not np.isfinite(affected_loc).all() or affected_loc.sum() <= 0:
        return 'local', 0
    aff_c = np.bincount(ctx.loc_c, weights=affected_loc, minlength=ctx.C)
    reached = np.flatnonzero((aff_c >= MIN_PEOPLE) & (aff_c >= MIN_SHARE * ctx.c_pop))
    n = len(reached)
    continents = {ctx.world.countries[ctx.iso3[c]].continent for c in reached
                  if ctx.iso3[c] in ctx.world.countries and ctx.world.countries[ctx.iso3[c]].continent}
    if n >= GLOBAL_COUNTRIES and (len(continents) >= GLOBAL_CONTINENTS or not continents):
        return 'global', n
    if n >= 2:
        return 'multi_country', n
    c = int(reached[0]) if n else int(np.argmax(aff_c))
    if aff_c[c] >= NATIONAL_SHARE * ctx.c_pop[c]:
        return 'national', n
    places = int(((affected_loc >= MIN_PEOPLE) & (ctx.loc_c == c)).sum())
    return ('regional' if places >= 2 else 'local'), n


def band(ratio: float) -> str:
    return next(label for limit, label in BANDS if ratio < limit)


def _pct(vals) -> dict | None:
    v = np.asarray([x for x in vals if x is not None and np.isfinite(x)], dtype=float)
    if not len(v):
        return None
    p5, p50, p95 = np.percentile(v, [5, 50, 95])
    return {'p5': float(p5), 'p50': float(p50), 'p95': float(p95)}


def _distribution(classes: list[str]) -> dict[str, float]:
    return {c: classes.count(c) / max(len(classes), 1) for c in REACH}


def _mode(dist: dict[str, float]) -> str:
    return max(REACH, key=lambda c: (dist[c], REACH.index(c)))


def position(run, comparisons: list[dict]) -> str:
    """Where the median headline outcome sits among the analogs with the same metric, in words."""
    key, name, unit = run.module.outcome_spec[0]
    rows = sorted((c for c in comparisons if c['metric'] == key), key=lambda c: c['value'])
    if not rows:
        return 'No historical analog with a comparable measured outcome in the library yet.'
    sim = rows[0]['sim']['p50']
    below = [r for r in rows if r['value'] <= sim]
    above = [r for r in rows if r['value'] > sim]
    if below and above:
        return f'Median {name.lower()} sits between {below[-1]["name"]} and {above[0]["name"]}.'
    if above:
        return f'Median {name.lower()} is below every analog in the library; the smallest is {above[0]["name"]}.'
    return f'Median {name.lower()} is above every analog in the library; the largest is {below[-1]["name"]}.'


def compare_analogs(run, k: int = 8) -> list[dict]:
    spec, mod = run.config.spec, run.module
    names = {key: (name, unit) for key, name, unit in mod.outcome_spec}
    out = []
    for a in analogs.search(spec.prompt, spec.event_type, k):
        if a.get('module') != mod.name:
            continue
        for key, value in a.get('metrics', {}).items():
            if key not in names or not value:
                continue
            sim = _pct(tr.outcomes.get(key, np.nan) for tr in run.ensemble)
            if not sim:
                continue
            ratio = sim['p50'] / value
            out.append({'analog_id': a['id'], 'name': a['name'], 'metric': key, 'metric_name': names[key][0], 'unit': names[key][1],
                        'value': float(value), 'definition': a.get('definition', ''), 'source': a['source'], 'sim': sim,
                        'ratio': ratio, 'band': band(ratio), 'inside_90': sim['p5'] <= value <= sim['p95']})
    return out


def measure(run) -> dict:
    classes, counts = [], []
    for tr in run.ensemble:
        c, n = reach_class(run.ctx, tr.affected_loc)
        classes.append(c)
        counts.append(n)
    dist = _distribution(classes)
    comparisons = compare_analogs(run)
    out = {'reach': {'distribution': dist, 'mode': _mode(dist), 'median_member': classes[run.median] if classes else 'local',
                     'countries': _pct(counts)},
           'magnitude': comparisons, 'position': position(run, comparisons), 'headline_metric': run.module.outcome_spec[0][0]}
    hyp = run.config.spec.scale
    if hyp:
        measured_band = {c['analog_id']: c['band'] for c in comparisons if c['metric'] == run.module.outcome_spec[0][0]}
        out['forecast'] = {'reach_expected': hyp.reach_expected, 'reach_hit': hyp.reach_expected == out['reach']['mode'],
                           'reach_share': dist.get(hyp.reach_expected, 0.0),
                           'bands': [{'analog_id': b.analog_id, 'expected': b.band, 'measured': measured_band.get(b.analog_id),
                                      'hit': measured_band.get(b.analog_id) == b.band} for b in hyp.analog_bands]}
    return out


def default_branches(run) -> list[dict]:
    """Rule-based escalation and containment paths: the three most influential priors (by sensitivity swing) pushed
    toward the tail that enlarges or shrinks the headline outcome."""
    out = [{'id': 'no_response', 'title': 'No response: none of the actor policies is taken', 'path': 'every actor stands by whatever the trigger shows',
            'trigger': 'actors without the capacity or will to act', 'likelihood': None, 'tails': [], 'disable_policies': True, 'generator': 'rules'}] \
        if run.config.spec.policies else []
    rows = [r for r in run.sensitivity[:3] if r['swing'] > 0]
    if not rows:
        return out
    up = [{'key': r['key'], 'side': 'upper' if r['outcome_high'] >= r['outcome_low'] else 'lower'} for r in rows]
    down = [{'key': t['key'], 'side': 'lower' if t['side'] == 'upper' else 'upper'} for t in up]
    names = ', '.join(r['text'].split(' (')[0].lower() for r in rows)
    return [{'id': 'escalation', 'title': 'Escalation: the most influential assumptions at their outcome-enlarging end', 'path': names,
             'trigger': 'evidence that these assumptions sit in their upper risk tail', 'likelihood': None, 'tails': up, 'generator': 'rules'},
            {'id': 'containment', 'title': 'Containment: the same assumptions at their outcome-shrinking end', 'path': names,
             'trigger': 'evidence that these assumptions sit in their favorable tail', 'likelihood': None, 'tails': down, 'generator': 'rules'}] + out


def size_branches(run, branches: list[dict], n: int | None = None) -> list[dict]:
    from .engine import central, sample_params
    n = min(n or BRANCH_N, max(len(run.ensemble), 1))
    seed, key = run.config.seed, run.module.outcome_spec[0][0]
    priors = {p.key: p for p in run.priors}
    base = [tr.outcomes.get(key, np.nan) for tr in run.ensemble]
    # larger or smaller is judged against the same n paired members; the k-of-N count then uses every base run
    base_med = float(np.nanmedian(base[:n])) if np.isfinite(base[:n]).any() else float('nan')
    out, spec = [], run.ctx.spec
    for b in branches:
        tails = [(t['key'], t['side']) for t in b.get('tails', []) if t['key'] in priors and priors[t['key']].high > priors[t['key']].low]
        off = bool(b.get('disable_policies')) and bool(spec.policies)
        vals, classes, saved = [], [], spec.policies
        if off:
            spec.policies = []  # same pattern as counterfactuals: the members re-run without any actor decision
        try:
            for i in range(n):
                params = central(run.priors) if i == 0 else sample_params(run.priors, np.random.default_rng([seed, i]))
                u = np.random.default_rng([seed, i, 3])
                for k, side in tails:
                    q = u.uniform(0.75, 1.0) if side == 'upper' else u.uniform(0.0, 0.25)
                    params[k] = priors[k].quantile(q)
                tr = run.module.simulate(run.ctx, params, np.random.default_rng([seed, i, 1]), detail=False)  # paired with base member i
                vals.append(tr.outcomes.get(key, np.nan))
                classes.append(reach_class(run.ctx, tr.affected_loc)[0])
        finally:
            spec.policies = saved
        size = _pct(vals)
        row = {**b, 'tails': [{'key': k, 'side': s} for k, s in tails], 'size': size, 'reach': _distribution(classes), 'n': n}
        if size and np.isfinite(base_med):
            larger = size['p50'] >= base_med
            k = int(sum(1 for v in base if np.isfinite(v) and (v >= size['p50'] if larger else v <= size['p50'])))
            share = k / len(base)
            row['exceedance'] = {'k': k, 'n': len(base), 'direction': 'at least' if larger else 'at most', 'value': size['p50']}
            row['computed_likelihood'] = 'unlikely' if share < 0.1 else 'possible' if share < 1 / 3 else 'likely'
        out.append(row)
    return out


def calibration_record(run) -> dict:
    """One line of runs/calibration.jsonl: the pre-registered forecast next to what the engine measured, keyed by
    snapshot and engine version. `truth` stays empty until a historical outcome is attached (data phase)."""
    spec, s, key = run.config.spec, run.scale, run.module.outcome_spec[0][0]
    m = s['measurement']
    return {'run_id': run.config.run_id, 'created_at': run.config.created_at, 'engine': run.config.engine_version, 'snapshot': run.config.data_snapshot,
            'module': run.module.name, 'event_type': spec.event_type, 'prompt': spec.prompt,
            'plausibility': spec.plausibility.verdict if spec.plausibility else None,
            'forecast': spec.scale.model_dump() if spec.scale else None,
            'measured': {'reach': m['reach'], 'headline': {'metric': key, **(_pct([tr.outcomes.get(key, np.nan) for tr in run.ensemble]) or {})},
                         'bands': [{'analog_id': x['analog_id'], 'metric': x['metric'], 'band': x['band']} for x in m['magnitude']],
                         'forecast_hits': m.get('forecast')},
            'branches': [{'id': b['id'], 'likelihood': b.get('likelihood'), 'computed_likelihood': b.get('computed_likelihood'),
                          'exceedance': b.get('exceedance')} for b in s['branches']],
            'truth': None}


def assess(run) -> dict:
    """Plausibility (from the spec) + measured reach and magnitude + sized escalation paths. Called in engine.finish()."""
    spec = run.config.spec
    hyp = spec.scale
    branches = [b.model_dump() for b in hyp.branches] if hyp and hyp.branches else default_branches(run)
    return {'plausibility': spec.plausibility.model_dump() if spec.plausibility else None,
            'hypothesis': hyp.model_dump() if hyp else None,
            'measurement': measure(run),
            'branches': size_branches(run, branches)}
