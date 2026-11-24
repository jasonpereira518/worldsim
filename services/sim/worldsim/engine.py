"""Run orchestration: context → ensemble → median run → frames → sensitivity → report."""
from __future__ import annotations

import math
import os
import threading
import time
from dataclasses import dataclass, field
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache

import numpy as np

from . import ENGINE_VERSION, llm, modules, voices
from .institutions import build_institutions
from .models import Assumption, Bubble, Delta, Frame, Persona, RunConfig, ScenarioSpec, SimEvent, Summary, SummaryMetric, Why
from .modules.base import STATUS, Context, Module, Prior, Trajectory, behavior_priors, policy_priors, stance_of
from .parse import find_companies
from .personas import Population, build_population
from .util import add_days, fmt
from .world import World, world

STATUS_NAMES = list(STATUS)
ENSEMBLE = int(os.environ.get('WORLDSIM_ENSEMBLE', 24))
PEOPLE_PER_STEP = 10
VOICE_CALLS, VOICE_USD = 60, 0.18  # persona voices get their own share of the run budget, so the reporter and critic still run
VOICE_WORKERS = 8
STATUS_WEIGHT = np.array([0, 0.6, 1.0, 1.25, 1.1, 1.25, 1.15])


@lru_cache(maxsize=2)
def population_for(snapshot_id: str) -> Population:
    return build_population(world())


@dataclass
class Run:
    config: RunConfig
    ctx: Context
    module: Module
    priors: list[Prior]
    overrides: dict[str, float]
    personas: list[Persona] = field(default_factory=list)
    ensemble: list[Trajectory] = field(default_factory=list)
    params: list[dict] = field(default_factory=list)
    median: int = 0
    traj: Trajectory | None = None
    frames: list[Frame] = field(default_factory=list)
    summary: Summary | None = None
    report: dict | None = None
    sensitivity: list[dict] = field(default_factory=list)
    counterfactuals: list[dict] = field(default_factory=list)
    scale: dict | None = None
    futures: dict = field(default_factory=dict)  # background agent calls (api.py)
    audit: list = field(default_factory=list)    # agent call records not yet written to runs/<id>.agents.jsonl
    agent_state: dict = field(default_factory=dict)  # {'setup_done': bool, 'steps': [AgentStep]} from the run file
    budget: llm.Budget = field(default_factory=llm.Budget)
    timings: dict[str, float] = field(default_factory=dict)
    done: threading.Event = field(default_factory=threading.Event)
    lock: threading.Lock = field(default_factory=threading.Lock)  # one pipeline per run (api.completed)
    error: str | None = None


def prepare(config: RunConfig, overrides: dict[str, float] | None = None, w: World | None = None) -> Run:
    w = w or world()
    spec = config.spec
    if spec.module == 'launch':
        from .modules.launch import Launch
        start, lead = Launch.prepare(spec)
        spec.start_date = start
    pop = population_for(w.snapshot_id) if w is world() else build_population(w)
    companies = find_companies(spec.prompt, w)
    inst = build_institutions(w, spec, companies)
    ctx = Context(w, pop, spec, inst)
    if spec.module == 'launch':
        ctx.launch_lead_weeks = lead
    for i in inst:
        from .world import haversine_km
        i.loc = int(np.argmin(haversine_km(i.lat, i.lon, ctx.loc_lat, ctx.loc_lon)))
    mod = modules.get(spec.module)
    overrides = dict(overrides or {})
    for a in spec.assumptions:  # user-edited numeric assumptions fix the matching prior
        if a.origin == 'user' and isinstance(a.value, (int, float)):
            overrides.setdefault(a.id, float(a.value))
    run = Run(config, ctx, mod, derive_priors(ctx, mod, overrides), overrides)
    run.personas = persona_models(ctx)
    return run


def derive_priors(ctx: Context, mod: Module, overrides: dict[str, float]) -> list[Prior]:
    """Module priors + actors' policy priors, moved by agent assumptions, then fixed by user overrides. Called again
    when setup agents change the spec (refresh_priors)."""
    ctx._policy_scope = None
    # actors' thresholds, lags and durations, then crowd behavior multipliers: appended, so module draws are unchanged
    priors = mod.priors(ctx) + policy_priors(ctx, mod.policy_menu) + behavior_priors(ctx, mod.behavior_dims)
    apply_llm_assumptions(priors, ctx.spec, overrides)
    for p in priors:
        if p.key in overrides:
            p.value = p.low = p.high = overrides[p.key]
    return priors


def refresh_priors(run: Run) -> None:
    run.priors = derive_priors(run.ctx, run.module, run.overrides)


def apply_llm_assumptions(priors: list[Prior], spec: ScenarioSpec, overrides: dict[str, float]) -> None:
    """Agent-set values (origin 'llm') move a prior inside its code-defined range: they may narrow it, never widen it,
    and a user override of the same key wins. The prior keeps its confidence; its origin and source become the agent's."""
    agent = {a.id: a for a in spec.assumptions if a.origin == 'llm' and isinstance(a.value, (int, float))}
    for p in priors:
        a = agent.get(p.key)
        if a is None or p.key in overrides:
            continue
        lo = max(p.low, a.low) if a.low is not None else p.low
        hi = min(p.high, a.high) if a.high is not None else p.high
        if lo > hi:
            continue
        p.value, p.low, p.high = min(max(float(a.value), lo), hi), lo, hi
        p.origin, p.source = 'llm', a.source


def persona_models(ctx: Context) -> list[Persona]:
    out = []
    for p in ctx.pop.people:
        out.append(Persona(id=p.id, kind='people', label=p.label, segment=p.segment,
                           location={'lat': p.lat, 'lon': p.lon, 'admin1': p.admin1, 'country_iso3': p.iso3, 'city': p.city},
                           population_represented=round(p.pop), demographics=p.demographics, traits=p.traits, context=p.context, voice=p.voice))
    for i in ctx.institutions:
        out.append(Persona(id=i.id, kind='institution', label=i.label, segment=i.role,
                           location={'lat': i.lat, 'lon': i.lon, 'admin1': '', 'country_iso3': i.iso3, 'city': ctx.loc_name[i.loc]},
                           population_represented=float(i.employees or 0),
                           demographics={'role': i.role.replace('_', ' '), 'employees': f'{i.employees:,.0f}' if i.employees else 'not modeled'},
                           traits={'risk_tolerance': 0.3, 'institutional_trust': 0.8, 'media_exposure': 0.9, 'price_sensitivity': 0.3,
                                   'tech_adoption': 0.6, 'social_connectedness': 0.9},
                           context={'country_profile_ref': i.iso3, 'relevant_companies': [i.company_id] if i.company_id else [],
                                    'local_conditions': [f'{i.role.replace("_", " ")} persona']}, voice=i.voice))
    return out


def sample_params(priors: list[Prior], rng: np.random.Generator) -> dict[str, float]:
    return {p.key: p.sample(rng) for p in priors}


def central(priors: list[Prior]) -> dict[str, float]:
    return {p.key: p.value for p in priors}


def run_ensemble(run: Run, n: int = ENSEMBLE, progress=None) -> None:
    t0 = time.perf_counter()
    seed = run.config.seed
    for i in range(n):
        rng = np.random.default_rng([seed, i])
        params = central(run.priors) if i == 0 else sample_params(run.priors, rng)
        traj = run.module.simulate(run.ctx, params, np.random.default_rng([seed, i, 1]), detail=False)
        run.params.append(params)
        run.ensemble.append(traj)
        if progress:
            progress(i + 1, n)
    finals = np.array([tr.key[-1] for tr in run.ensemble])
    med = np.median(finals)
    run.median = int(np.argmin(np.abs(finals - med)))
    run.timings['ensemble_s'] = time.perf_counter() - t0
    t1 = time.perf_counter()
    run.traj = run.module.simulate(run.ctx, run.params[run.median], np.random.default_rng([seed, run.median, 1]), detail=True)
    run.timings['detail_s'] = time.perf_counter() - t1
    assert abs(run.traj.key[-1] - run.ensemble[run.median].key[-1]) < 1e-6 * max(1, abs(run.traj.key[-1])), 'detail run diverged from its ensemble member'


def quick_look(run: Run, n: int) -> dict:
    """The first n ensemble members (same seeds as the full ensemble, so paired with it) for the actors' re-plan:
    headline outcome and, per policy, in how many runs it fired and when."""
    seed, (key, name, unit) = run.config.seed, run.module.outcome_spec[0]
    vals, fired = [], {p.id: [] for p in run.config.spec.policies}
    for i in range(n):
        params = central(run.priors) if i == 0 else sample_params(run.priors, np.random.default_rng([seed, i]))
        tr = run.module.simulate(run.ctx, params, np.random.default_rng([seed, i, 1]), detail=False)
        vals.append(float(tr.outcomes.get(key, np.nan)))
        for pid in {d['policy'] for d in tr.decisions}:
            fired.setdefault(pid, []).append(min(d['day'] for d in tr.decisions if d['policy'] == pid))
    p5, p50, p95 = np.nanpercentile(vals, [5, 50, 95])
    return {'n': n, 'outcome': {'name': name, 'unit': unit, 'p5': float(p5), 'p50': float(p50), 'p95': float(p95)},
            'fired': {pid: {'runs': len(days), 'median_day': float(np.median(days)) if days else None} for pid, days in fired.items()}}


def bands(run: Run) -> np.ndarray:
    keys = np.stack([tr.key for tr in run.ensemble])
    return np.percentile(keys, [5, 25, 50, 75, 95], axis=0)


def frames(run: Run):
    """Yield Frame objects for the median run."""
    ctx, tr, mod, spec = run.ctx, run.traj, run.module, run.config.spec
    band = bands(run)
    prev_p = np.zeros(ctx.P, np.int8)
    prev_i = np.zeros(ctx.I, np.int8)
    prev_pm = np.zeros(ctx.P, np.float32)
    reached: set[int] = set()
    price = run.params[run.median].get('price_usd')
    origin_name = spec.origin.name if spec.origin else 'abroad'
    partner = getattr(ctx, 'partner_name', '')
    mname, munit = mod.persona_metric
    spoken = np.zeros(ctx.P, np.float32)  # metric value at the persona's last bubble
    vb = run.budget.child(VOICE_USD, VOICE_CALLS)
    steps = []  # pass 1 picks every step's speakers; pass 2 adds the voices and yields
    for t in range(ctx.steps + 1):
        date = add_days(spec.start_date, t * ctx.dt)
        ps, pm = tr.p_status[t], tr.p_metric[t]
        changed = np.flatnonzero(ps != prev_p)
        deltas = [Delta(id=run.personas[k].id, status=STATUS_NAMES[ps[k]], metric=round(float(pm[k]), 3)) for k in changed]
        ichanged = np.flatnonzero(tr.i_status[t] != prev_i)
        for j in ichanged:
            deltas.append(Delta(id=ctx.institutions[j].id, status=STATUS_NAMES[tr.i_status[t, j]], metric=round(float(tr.i_metric[t, j]), 3)))
        # choose bubbles: most important changes this step
        grew = np.flatnonzero((ps > 0) & (pm >= 2 * np.maximum(spoken, 1e-6)) & (pm > 0) & (spoken > 0))
        cand = np.union1d(changed[ps[changed] > 0], grew)
        items, payload, inst_ids = [], {}, set()
        if len(cand):
            first = np.array([ctx.p_c[k] not in reached for k in cand])
            novelty = np.where(np.isin(cand, changed), 1.0, 0.8)
            pri = np.log10(np.maximum(ctx.p_pop[cand], 10)) * STATUS_WEIGHT[ps[cand]] * np.where(first, 1.8, 1.0) * novelty
            order = cand[np.argsort(-pri)][:PEOPLE_PER_STEP]
            spoken[order] = np.maximum(pm[order], 1e-3)
            for k in cand:
                if ps[k] >= STATUS['reacting']:
                    reached.add(int(ctx.p_c[k]))
            pri_map = dict(zip(cand.tolist(), pri.tolist()))
            picks = [(int(k), 'people') for k in order] + [(int(j), 'institution') for j in ichanged]
            inst_ids = {ctx.institutions[k].id for k, kind in picks if kind == 'institution'}
            for k, kind in picks:
                if kind == 'people':
                    per = run.personas[k]
                    old, new = STATUS_NAMES[prev_p[k]], STATUS_NAMES[ps[k]]
                    before, after = float(prev_pm[k]), float(pm[k])
                    if old == new:
                        old = f'{new} ({mname} doubled)'
                    income = ctx.p_income[k]
                    tctx = {'city': per.location['city'].replace('Rest of ', ''), 'country': ctx.c_name[ctx.p_c[k]],
                            'm': voices.metric_text(after, munit), 'unit': munit, 'source': origin_name, 'partner': partner,
                            'price': f'{price:,.0f}' if price else '', 'price_share': f'{price / (income / 12) * 100:.0f}%' if price and np.isfinite(income) and income > 0 else 'a big share'}
                    role, pid, prio = None, per.id, pri_map[k]
                else:
                    inst = ctx.institutions[k]
                    per = next(p for p in run.personas if p.id == inst.id)
                    old, new = STATUS_NAMES[prev_i[k]], STATUS_NAMES[tr.i_status[t, k]]
                    before = float(tr.i_metric[t - 1, k]) if t else 0.0
                    after = float(tr.i_metric[t, k])
                    tctx = {'city': ctx.loc_name[inst.loc], 'country': ctx.c_name[ctx.c_idx.get(inst.iso3, 0)] if inst.iso3 in ctx.c_idx else inst.iso3,
                            'm': mod.inst_text(inst.role, after), 'source': origin_name, 'partner': partner}
                    role, pid, prio = inst.role, inst.id, 9.0 + (2 if new == 'affected' else 0)
                text = voices.template(spec.module, new, tctx, pid, per.kind, role)
                wname, wunit = mod.inst_metric(role) if per.kind == 'institution' else (mname, munit)
                why = Why(event=f'{old} → {new}', metric=wname, before=round(before, 3), after=round(after, 3), unit=wunit)
                payload[pid] = (text, why, prio, new)
                items.append({'id': pid, 'who': per.label, 'voice': per.voice, 'traits': per.traits, 'change': f'{old} → {new}',
                              'crowd': stance_of(ctx, int(ctx.p_c[k])) if kind == 'people' and spec.behavior else None,
                              'numbers': f'{mname} {before:.3g} → {after:.3g} {munit}; ' + ', '.join(f'{k}={v}' for k, v in tctx.items() if k in ('price', 'price_share', 'm'))})
        steps.append((t, date, deltas, payload, items, inst_ids))
        prev_p, prev_i, prev_pm = ps, tr.i_status[t], pm

    def speak(t, items, inst_ids):
        # routine reactions on the fast model; key actors (institutions) on the mid-tier model
        out = voices.llm_batch([i for i in items if i['id'] not in inst_ids][:8], vb, t)
        out.update(voices.llm_batch([i for i in items if i['id'] in inst_ids][:4], vb, t, model=llm.MID_MODEL))
        return out

    stored = run.agent_state.get('voices', {})  # lines from the first stream, so a replay makes no calls
    live = [s for s in steps if s[4] and str(s[0]) not in stored] if llm.enabled() else []
    # every step's voice calls start now and run ahead of playback (in step order, so the budget favors early steps);
    # one step at a time made a 365-step outbreak wait about 6 minutes on them
    # ponytail: up to VOICE_WORKERS calls in flight can overshoot the voice cap by that many calls
    ex = ThreadPoolExecutor(VOICE_WORKERS) if live else None
    futs = {s[0]: ex.submit(speak, s[0], s[4], s[5]) for s in live}
    t_voice = time.perf_counter()
    try:
        for t, date, deltas, payload, items, _ in steps:
            if t in futs:
                llm_lines = run.agent_state.setdefault('voices', {})[str(t)] = futs[t].result()
            else:
                llm_lines = stored.get(str(t), {})
            bubbles: list[Bubble] = []
            said = set()
            for pid, (text, why, prio, new) in payload.items():
                l = llm_lines.get(pid)
                if not l and text in said:
                    continue
                said.add(text)
                bubbles.append(Bubble(id=f'b_{t}_{pid}', persona_id=pid, t=t, text=l['text'] if l else text, sentiment=voices.SENTIMENT.get(new, 0),
                                      priority=round(prio, 2), why=why, decision=l['decision'] if l else None, emotion=l['emotion'] if l else None,
                                      generator='llm' if l else 'template'))
            events = [SimEvent(id=f'e_{t}_{i}', t=t, date=date, title=e['title'], cause=e['cause'], places=e.get('places', []), severity=e['severity'])
                      for i, e in enumerate(ev for ev in tr.events if ev['t'] == t)]
            metrics = {k: float(v) for k, v in tr.metrics[t].items()}
            yield Frame(t=t, date=date, deltas=deltas, bubbles=bubbles, events=events,
                        flows=[{'from': f['from'], 'to': f['to'], 'weight': round(f['weight'], 3), 'kind': f['kind']} for f in (tr.flows[t] if tr.flows else [])],
                        metrics=metrics, layers=tr.layers[t] if tr.layers else {}, band=[round(float(b), 4) for b in band[:, t]])
    finally:
        if ex:
            ex.shutdown(wait=False, cancel_futures=True)  # a closed stream stops queued calls
    if futs:
        r = vb.report()
        run.audit.append({'role': 'voices', 'model': f'{llm.FAST_MODEL}, {llm.MID_MODEL}', 'ok': True, 'usd': r['usd'], 'calls': r['calls'],
                          'cache_hits': r['cache_hits'], 'refusals': r['refusals'], 'errors': r['errors'],
                          'seconds': round(time.perf_counter() - t_voice, 2), 'evidence': [], 'output': None})


def sensitivity(run: Run, top: int = 5) -> list[dict]:
    """One-at-a-time swings of the key outcome at each prior's low and high end, other parameters central."""
    base = central(run.priors)
    seed = run.config.seed
    rows = []
    ref = run.module.simulate(run.ctx, base, np.random.default_rng([seed, 0, 1]), detail=False).key[-1]
    for p in run.priors:
        if p.high <= p.low:
            continue
        vals = []
        for v in (p.low, p.high):
            params = dict(base, **{p.key: v})
            vals.append(float(run.module.simulate(run.ctx, params, np.random.default_rng([seed, 0, 1]), detail=False).key[-1]))
        rows.append({'key': p.key, 'text': p.text, 'unit': p.unit, 'low': p.low, 'high': p.high, 'central': p.value,
                     'outcome_low': vals[0], 'outcome_high': vals[1], 'outcome_central': float(ref), 'swing': abs(vals[1] - vals[0]),
                     'origin': p.origin, 'source': p.source})
    rows.sort(key=lambda r: -r['swing'])
    run.sensitivity = rows[:top]
    return run.sensitivity


def counterfactuals(run: Run) -> list[dict]:
    out = []
    base = central(run.priors)
    seed = run.config.seed
    ref = float(run.module.simulate(run.ctx, base, np.random.default_rng([seed, 0, 1]), detail=False).key[-1])
    for cf in getattr(run.module, 'counterfactuals', lambda ctx: [])(run.ctx):
        params = dict(base, **cf.get('params', {}))
        saved = run.ctx.spec.interventions
        run.ctx.spec.interventions = saved + cf.get('interventions', [])
        try:
            val = float(run.module.simulate(run.ctx, params, np.random.default_rng([seed, 0, 1]), detail=False).key[-1])
        finally:
            run.ctx.spec.interventions = saved
        out.append({'action': cf['action'], 'trigger': cf.get('trigger', ''), 'outcome': val, 'baseline': ref,
                    'change_pct': (val - ref) / ref * 100 if ref else float('nan')})
    run.counterfactuals = out
    return out


def summary(run: Run) -> Summary:
    mod, ens = run.module, run.ensemble
    metrics = []
    for key, name, unit in mod.outcome_spec:
        vals = np.array([tr.outcomes.get(key, np.nan) for tr in ens], dtype=float)
        vals = vals[np.isfinite(vals)]
        if not len(vals):
            continue
        p5, p25, p50, p75, p95 = np.percentile(vals, [5, 25, 50, 75, 95])
        metrics.append(SummaryMetric(name=name, value=round(float(p50), 4), unit=unit, low=round(float(p5), 4), high=round(float(p95), 4),
                                     low50=round(float(p25), 4), high50=round(float(p75), 4), confidence=confidence(run)))
    k = metrics[0] if metrics else None
    head = f'{run.config.spec.title}: median {fmt(k.value)} {k.name.lower()} (90% interval {fmt(k.low)}–{fmt(k.high)}, {k.unit}) by {add_days(run.config.spec.start_date, run.ctx.steps * run.ctx.dt)}.' if k else run.config.spec.title
    return Summary(headline=head + f' {len(ens)}-run ensemble; simulation, not a forecast.', metrics=metrics,
                   note=f'{len(ens)} stochastic runs of the {mod.name} module; the map shows the median run. Ranges are 5th–95th percentiles.')


LOW_PRIOR_LIMIT = 12


def confidence(run: Run) -> str:
    """One rule for every output: low without data, in generic mode, or when many low-confidence priors drive the run."""
    # actor-policy priors are decisions, not unknowns about the world: they do not count toward the low-confidence limit
    lows = [p for p in run.priors if p.confidence == 'low' and p.high > p.low and not p.key.startswith('pol_')]
    if not run.ctx.world.available or run.module.name == 'generic' or len(lows) > LOW_PRIOR_LIMIT:
        return 'low'
    return run.module.confidence


def execute(run: Run, progress=None) -> None:
    """Full pipeline without streaming (used by tests, exports and replays)."""
    run_ensemble(run, progress=progress)
    run.frames = list(frames(run))
    finish(run)


def finish(run: Run) -> None:
    from .report import build_report
    from .scale import assess
    sensitivity(run)
    counterfactuals(run)
    run.scale = assess(run)
    run.summary = summary(run)
    run.report = build_report(run)
    run.done.set()


def make_config(spec: ScenarioSpec, seed: int, run_id: str, snapshot: str, parent: str | None = None, branch_at: int | None = None,
                label: str | None = None) -> RunConfig:
    import datetime as dt
    return RunConfig(run_id=run_id, seed=seed, spec=spec, created_at=dt.datetime.now(dt.UTC).isoformat(timespec='seconds'),
                     data_snapshot=snapshot, engine_version=ENGINE_VERSION, ensemble_size=ENSEMBLE, parent_run_id=parent,
                     branch_at=branch_at, label=label)
