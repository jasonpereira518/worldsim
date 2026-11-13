"""Agents: Claude roles that choose and judge; the engine computes. A dict of roles and plain functions, no orchestrator.

Every role is optional. With WORLDSIM_LLM off, over budget, refused or failing, the caller keeps its rule-based path.
Validation here is the contract: categorical fields only for likelihoods and reach, prior keys checked against the
module's priors, analog ids against the library, and prose stripped of any sentence with a number that neither the
input nor a tool result contains. Decisions are written into the ScenarioSpec, so replays never call the API;
`runs/<id>.agents.jsonl` is an audit log of every call (role, model, cost, evidence, raw output)."""
from __future__ import annotations

import json
import logging
import re
import threading
import time
from pathlib import Path
from typing import Callable, get_args

import numpy as np

from . import T0, analogs, llm
from .evidence import Evidence, _obj
from .models import (AgentStep, AnalogBand, Assumption, CrowdStance, EscalationBranch, EventType, Plausibility, Policy, PriorTail, ScaleHypothesis,
                     ScenarioSpec, StanceLabel)
from .modules.base import policy_rows, scope_mask
from .scale import REACH
from .voices import numbers_ok

ROLES = {
    'intake': {'model': llm.MAIN_MODEL, 'effort': 'low', 'prompt': 'agent_intake', 'tools': ['find_place', 'get_country', 'search_analogs'],
               'cap': 0.12, 'turns': 3},
    'scale': {'model': llm.MAIN_MODEL, 'effort': 'medium', 'prompt': 'agent_scale',
              'tools': ['get_country', 'get_indicator_series', 'search_analogs', 'list_priors'], 'cap': 0.22, 'turns': 4},
    'calibrator': {'model': llm.MID_MODEL, 'effort': 'medium', 'prompt': 'agent_calibrator',
                   'tools': ['list_priors', 'get_country', 'get_indicator_series', 'search_analogs', 'get_company'], 'cap': 0.10, 'turns': 4},
    'actors': {'model': llm.MID_MODEL, 'effort': 'medium', 'prompt': 'agent_actors', 'tools': ['get_country', 'get_indicator_series', 'search_analogs'],
               'cap': 0.10, 'turns': 3},
    'replan': {'model': llm.MID_MODEL, 'effort': 'low', 'prompt': 'agent_actors', 'tools': [], 'cap': 0.08, 'turns': 1},
    'crowds': {'model': llm.FAST_MODEL, 'effort': 'low', 'prompt': 'agent_crowds', 'tools': [], 'cap': 0.04, 'turns': 1},
    'critic': {'model': llm.MID_MODEL, 'effort': 'low', 'prompt': 'agent_critic', 'tools': [], 'cap': 0.05, 'turns': 1},
}
RUNNING = {'calibrator': 'Checking model parameters against country data and past events',
           'actors': 'Deciding how governments and agencies respond', 'replan': 'Actors reviewing a first look at the outcome',
           'crowds': 'Judging how populations will behave'}
MAX_POLICIES = 8
MAX_PROPOSALS = 8
_AUDIT_LOCK = threading.Lock()

STR, STRS = {'type': 'string'}, {'type': 'array', 'items': {'type': 'string'}}
NULLABLE = {'type': ['string', 'null']}
LIKELIHOOD = {'type': 'string', 'enum': ['unlikely', 'possible', 'likely']}
INTAKE_SCHEMA = _obj({
    'event_type': {'type': 'string', 'enum': list(get_args(EventType))}, 'origin_place': NULLABLE, 'is_global': {'type': 'boolean'},
    'needs_clarification': {'type': 'boolean'}, 'clarifying_question': NULLABLE, 'actors': STRS, 'mechanisms': STRS, 'title': STR,
    'plausibility': _obj({'verdict': {'type': 'string', 'enum': ['realistic', 'stretched', 'implausible', 'impossible']},
                          'reasons': STRS, 'adjusted_premise': NULLABLE}),
    'evidence': STRS,
})
SCALE_SCHEMA = _obj({
    'reach_expected': {'type': 'string', 'enum': REACH}, 'reach_why': STR,
    'analog_bands': {'type': 'array', 'items': _obj({'analog_id': STR, 'band': {'type': 'string', 'enum': ['far below', 'below', 'comparable', 'above', 'far above']},
                                                     'why': STR})},
    'branches': {'type': 'array', 'items': _obj({'title': STR, 'path': STR, 'trigger': STR, 'likelihood': LIKELIHOOD,
                                                 'tails': {'type': 'array', 'items': _obj({'key': STR, 'side': {'type': 'string', 'enum': ['upper', 'lower']}})},
                                                 'disable_policies': {'type': 'boolean'}})},
    'evidence': STRS,
})
NUMBER_OR_NULL = {'type': ['number', 'null']}
CALIBRATOR_SCHEMA = _obj({'proposals': {'type': 'array', 'items': _obj({'key': STR, 'value': {'type': 'number'}, 'low': NUMBER_OR_NULL,
                                                                        'high': NUMBER_OR_NULL, 'rationale': STR, 'evidence': STRS})}})


def clean_text(text: str | None, allowed: str) -> str:
    """Drop every sentence that states a number absent from `allowed` (the input plus retrieved evidence)."""
    parts = re.split(r'(?<=[.;!?])\s+', (text or '').strip())
    return ' '.join(p for p in parts if p and numbers_ok(p, allowed)).strip()


def slug(text: str, taken: set[str]) -> str:
    base = re.sub(r'[^a-z0-9]+', '_', text.lower()).strip('_')[:40] or 'branch'
    s, i = base, 2
    while s in taken:
        s, i = f'{base}_{i}', i + 1
    taken.add(s)
    return s


def run_role(role: str, user: str, schema: dict, ev: Evidence, budget: llm.Budget | None, audit: list | None = None) -> dict | None:
    r = ROLES[role]
    b = budget.child(r['cap']) if budget else llm.Budget(max_usd=r['cap'])
    t0 = time.perf_counter()
    out = llm.agent(llm.prompt(r['prompt']).replace('{t0}', T0), user, schema, ev.tools(r['tools']), model=r['model'], effort=r['effort'],
                    budget=b, max_turns=r['turns'])
    if audit is not None:
        audit.append({'role': role, 'model': r['model'], 'ok': out is not None, 'usd': round(b.usd, 5), 'calls': b.calls, 'cache_hits': b.cache_hits,
                      'refusals': b.refusals, 'errors': b.errors, 'seconds': round(time.perf_counter() - t0, 2), 'evidence': sorted(ev.seen), 'output': out})
    return out


def write_audit(path: Path, entries: list[dict]) -> None:
    if entries:
        path.parent.mkdir(parents=True, exist_ok=True)
        with _AUDIT_LOCK, path.open('a') as f:  # setup roles finish on parallel threads
            for e in entries:
                f.write(json.dumps(e, default=str) + '\n')


def intake(text: str, world, budget: llm.Budget | None = None, audit: list | None = None) -> dict | None:
    """Scenario fields plus a plausibility verdict. Prose with unsupported numbers is cut; the adjusted premise is a
    suggestion the user may accept (and then owns), so it keeps its numbers."""
    if not llm.enabled():
        return None
    ev = Evidence(world)
    out = run_role('intake', text, INTAKE_SCHEMA, ev, budget, audit)
    if not out:
        return None
    allowed = text + ' ' + ev.text()
    p = out.get('plausibility') or {}
    out['plausibility'] = Plausibility(verdict=p.get('verdict', 'realistic'), reasons=[r for r in (clean_text(x, allowed) for x in p.get('reasons', [])) if r],
                                       adjusted_premise=p.get('adjusted_premise') or None, generator='llm')
    out['title'] = clean_text(out.get('title'), allowed) or None
    out['mechanisms'] = [m for m in (clean_text(x, allowed) for x in out.get('mechanisms', [])) if m]
    return out


def scale_assessor(run, budget: llm.Budget | None = None, audit: list | None = None) -> ScaleHypothesis | None:
    """Pre-registered forecast of reach, magnitude band per analog, and escalation paths (as prior tails)."""
    if not llm.enabled():
        return None
    spec, mod = run.config.spec, run.module
    ev = Evidence(run.ctx.world, spec, run.priors)
    _, name, unit = mod.outcome_spec[0]
    user = json.dumps({'title': spec.title, 'prompt': spec.prompt, 'event_type': spec.event_type, 'module': mod.name,
                       'origin': f'{spec.origin.name}, {spec.origin.country}' if spec.origin else 'global', 'start_date': spec.start_date,
                       'horizon_days': spec.horizon_days, 'mechanisms': spec.mechanisms, 'headline_outcome': f'{name} ({unit})',
                       'plausibility': spec.plausibility.verdict if spec.plausibility else 'not assessed'}, indent=1)
    out = run_role('scale', user, SCALE_SCHEMA, ev, budget, audit)
    return validate_scale(out, run, user + ' ' + ev.text()) if out else None


def scenario_brief(run) -> dict:
    spec = run.config.spec
    return {'title': spec.title, 'prompt': spec.prompt, 'event_type': spec.event_type, 'module': run.module.name,
            'origin': f'{spec.origin.name}, {spec.origin.country} ({spec.origin.iso3})' if spec.origin else 'global',
            'start_date': spec.start_date, 'horizon_days': spec.horizon_days, 'actors': spec.actors, 'mechanisms': spec.mechanisms}


Setup = tuple[AgentStep, Callable[[ScenarioSpec], None] | None]


def calibrator(run, budget: llm.Budget | None = None, audit: list | None = None) -> Setup:
    """Evidence-backed central values (and optionally narrower ranges) for the module's priors, as origin-'llm'
    assumptions. Keys pinned by the user are off limits; proposals without retrieved evidence are discarded."""
    spec, role = run.config.spec, 'calibrator'
    pinned = set(run.overrides) | {a.id for a in spec.assumptions if a.origin == 'user'}
    open_priors = {p.key: p for p in run.priors if p.high > p.low and p.key not in pinned}
    ev = Evidence(run.ctx.world, spec, list(open_priors.values()))
    user = json.dumps({**scenario_brief(run), 'locked_by_user': sorted(pinned)}, indent=1)
    out = run_role(role, user, CALIBRATOR_SCHEMA, ev, budget, audit)
    if not out:
        return AgentStep(role=role, model=ROLES[role]['model'], status='failed', summary='No usable answer; the module defaults stand.'), None
    allowed = user + ' ' + ev.text()
    accepted, cited, rejected = [], set(), 0
    for pr in out.get('proposals', [])[:MAX_PROPOSALS]:
        key = pr['key'].removeprefix('prior:')
        p = open_priors.get(key)
        cites = [i for i in pr.get('evidence', []) if i in ev.seen]
        if p is None or not cites:
            rejected += 1
            continue
        lo = max(p.low, pr['low']) if pr.get('low') is not None else p.low
        hi = min(p.high, pr['high']) if pr.get('high') is not None else p.high
        if lo > hi:
            lo, hi = p.low, p.high
        why = clean_text(pr.get('rationale'), allowed)
        refs = '; '.join(f'{ev.seen[i]["title"]} ({ev.seen[i]["source"]})' for i in cites[:3])
        accepted.append(Assumption(id=key, text=p.text, value=round(min(max(pr['value'], lo), hi), 6), unit=p.unit, origin='llm',
                                   confidence=p.confidence, source=f'calibrator (AI): {why} Evidence: {refs}'.strip(), editable=True,
                                   low=round(lo, 6), high=round(hi, 6)))
        cited.update(cites)
    summary = f'Set {len(accepted)} parameter{"s" if len(accepted) != 1 else ""} from evidence' + \
              (f'; discarded {rejected} without a valid key or evidence' if rejected else '') + '.'
    usd = audit[-1]['usd'] if audit else 0.0

    def apply(s: ScenarioSpec) -> None:
        ids = {a.id for a in accepted}
        s.assumptions = [a for a in s.assumptions if not (a.origin == 'llm' and a.id in ids)] + accepted

    return AgentStep(role=role, model=ROLES[role]['model'], status='done', summary=summary, usd=usd, evidence=sorted(cited)), apply


def policy_menu(run) -> tuple[dict, list[str]]:
    """The module's menu as the agent sees it, and the scopes it may choose (origin, all, a World Bank income group)."""
    groups = sorted({c.income_group for c in run.ctx.world.countries.values() if c.income_group})
    scopes = (['origin'] if run.config.spec.origin else []) + ['all'] + [f'group:{g}' for g in groups]
    menu = {a: {'label': it['label'], 'trigger': it['metric_label'], 'level': it['level'], 'threshold_range': list(it['threshold'][1:3]),
                'threshold_unit': it['threshold'][3], 'lag_days_range': list(it['lag'][1:]), 'duration_days_range': list(it['duration'][1:]) if 'duration' in it else None,
                'scope': it.get('scope', 'choose'), 'source': it['source']} for a, it in run.module.policy_menu.items()}
    return menu, scopes


def actors_schema(menu: dict, scopes: list[str]) -> dict:
    return _obj({'policies': {'type': 'array', 'items': _obj({
        'actor': STR, 'action': {'type': 'string', 'enum': list(menu)}, 'scope': {'type': 'string', 'enum': scopes},
        'threshold': {'type': 'number'}, 'lag_days': {'type': 'number'}, 'duration_days': NUMBER_OR_NULL, 'rationale': STR, 'evidence': STRS})}})


def current_plan(run) -> list[dict]:
    vals = {p.key: p.value for p in run.priors}
    return [{'actor': pol.actor_label, 'action': pol.action, 'scope': pol.scope, 'threshold': vals.get(f'pol_{pol.id}_threshold'),
             'lag_days': vals.get(f'pol_{pol.id}_lag'), 'duration_days': vals.get(f'pol_{pol.id}_duration'), 'rationale': pol.rationale}
            for pol in run.config.spec.policies]


def validate_policies(out: dict, run, ev: Evidence, allowed: str, before: list[dict] | None = None) -> tuple[list[Policy], list[Assumption]]:
    """Menu actions only, one policy per (action, scope), the menu's fixed scope enforced, every number clamped to the
    menu range. The numbers become origin-'llm' assumptions on the policy's priors, so the ensemble still samples them."""
    items, (_, scopes) = run.module.policy_menu, policy_menu(run)
    prev = {(b['action'], b['scope']): b for b in before or []}
    policies, assumptions, seen = [], [], set()
    for e in out.get('policies', []):
        item = items.get(e['action'])
        scope = item.get('scope', e['scope']) if item else None
        if not item or scope not in scopes or (e['action'], scope) in seen or len(policies) >= MAX_POLICIES:
            continue
        seen.add((e['action'], scope))
        actor = ' '.join(e['actor'].split())[:60] or 'Government'
        why = clean_text(e.get('rationale'), allowed)
        pol = Policy(id=slug(f'{e["action"]} {scope}', set()), actor_id=slug(actor, set()), actor_label=actor, action=e['action'], scope=scope,
                     trigger_metric=item['metric'], rationale=why, evidence=[i for i in e.get('evidence', []) if i in ev.seen])
        asked = {'threshold': e['threshold'], 'lag': e['lag_days'], 'duration': e.get('duration_days')}
        vals = {}
        for key, text, c, lo, hi, unit in policy_rows(pol, item):
            v = asked[key.rsplit('_', 1)[1]]
            vals[key] = round(min(max(float(v if v is not None else c), lo), hi), 6)
            assumptions.append(Assumption(id=key, text=text, value=vals[key], unit=unit, origin='llm', confidence='low',
                                          source=f'actors (AI): {why}'.strip(), editable=True, low=lo, high=hi))
        if before is not None:
            b = prev.get((pol.action, scope))
            old = {f'pol_{pol.id}_{k}': b[f'{k}_days' if k != 'threshold' else k] for k in ('threshold', 'lag', 'duration')} if b else {}
            pol.revised = b is None or b['actor'] != actor or any(old.get(k) is None or abs(old[k] - v) > 1e-6 for k, v in vals.items())
        policies.append(pol)
    return policies, assumptions


def _policy_apply(policies: list[Policy], assumptions: list[Assumption]) -> Callable[[ScenarioSpec], None]:
    def apply(s: ScenarioSpec) -> None:
        s.policies = policies
        s.assumptions = [a for a in s.assumptions if not (a.origin == 'llm' and a.id.startswith('pol_'))] + assumptions
    return apply


def actors(run, budget: llm.Budget | None = None, audit: list | None = None) -> Setup:
    """One call for every actor: conditional policies chosen from the module's menu. The engine decides when each one
    fires (its trigger crosses the threshold in that ensemble member) and what it does."""
    role, spec = 'actors', run.config.spec
    menu, scopes = policy_menu(run)
    ev = Evidence(run.ctx.world, spec)
    user = json.dumps({**scenario_brief(run), 'policy_menu': menu, 'scopes': scopes}, indent=1)
    out = run_role(role, user, actors_schema(menu, scopes), ev, budget, audit)
    if not out:
        return AgentStep(role=role, model=ROLES[role]['model'], status='failed', summary='No usable answer; no actor policies, as with agents off.'), None
    policies, assumptions = validate_policies(out, run, ev, user + ' ' + ev.text())
    who = sorted({p.actor_label for p in policies})
    summary = (f'{len(policies)} conditional polic{"y" if len(policies) == 1 else "ies"} for {", ".join(who[:3])}' + (f' and {len(who) - 3} more' if len(who) > 3 else '') + '.'
               if policies else 'No policy from the menu fits this scenario.')
    usd = audit[-1]['usd'] if audit else 0.0
    return (AgentStep(role=role, model=ROLES[role]['model'], status='done', summary=summary, usd=usd, evidence=sorted({i for p in policies for i in p.evidence})),
            _policy_apply(policies, assumptions))


def replan(run, budget: llm.Budget | None = None, audit: list | None = None, *, look: dict) -> Setup:
    """The one re-plan round: actors see a first look at the outcome (headline percentiles; per policy, in how many runs
    it fired and when) and may revise once. Unchanged policies keep their ids; the first plan stays in the run file."""
    role, before = 'replan', current_plan(run)
    menu, scopes = policy_menu(run)
    ev = Evidence(run.ctx.world, run.config.spec)
    names = {p.id: f'{p.actor_label}: {p.action} ({p.scope})' for p in run.config.spec.policies}
    first = {**look, 'fired': {names.get(k, k): v for k, v in look['fired'].items()}}
    user = json.dumps({**scenario_brief(run), 'policy_menu': menu, 'scopes': scopes, 'current_plan': before, 'first_look': first}, indent=1)
    out = run_role(role, user, actors_schema(menu, scopes), ev, budget, audit)
    if not out:
        return AgentStep(role=role, model=ROLES[role]['model'], status='failed', summary='No usable answer; the first plan stands.'), None
    policies, assumptions = validate_policies(out, run, ev, user, before)
    dropped = len({(b['action'], b['scope']) for b in before} - {(p.action, p.scope) for p in policies})
    changed = sum(p.revised for p in policies)
    summary = (f'Revised {changed} and dropped {dropped} of {len(before)} policies' if changed or dropped else f'Kept all {len(before)} policies') + \
              f' after a first look at {look["n"]} runs.'
    usd = audit[-1]['usd'] if audit else 0.0
    return AgentStep(role=role, model=ROLES[role]['model'], status='done', summary=summary, usd=usd), _policy_apply(policies, assumptions)


CLUSTER_INDICATORS = ['gdp_per_capita_usd', 'urban_pct', 'internet_users_pct', 'age_65_plus_pct', 'physicians_per1000']


def clusters(run, ev: Evidence) -> list[dict]:
    """Population clusters a crowd agent speaks for: the origin country, then each World Bank income group, each with
    population-weighted indicators registered as citable evidence (cluster:<id>)."""
    w, ctx = run.ctx.world, run.ctx
    groups = sorted({c.income_group for c in w.countries.values() if c.income_group})
    out = []
    for cid in (['origin'] if run.config.spec.origin else []) + [f'group:{g}' for g in groups]:
        mask = scope_mask(ctx, cid)
        cs = [w.countries[ctx.iso3[i]] for i in np.flatnonzero(mask) if ctx.iso3[i] in w.countries]
        pop = sum(ctx.c_pop[i] for i in np.flatnonzero(mask))
        data = {'countries': len(cs), 'population': round(float(pop))}
        for k in CLUSTER_INDICATORS:
            vs = [(c.ind[k].value, ctx.c_pop[ctx.c_idx[c.iso3]]) for c in cs if c.ind.get(k) and c.iso3 in ctx.c_idx]
            if vs and sum(wt for _, wt in vs) > 0:
                data[k] = round(sum(v * wt for v, wt in vs) / sum(wt for _, wt in vs), 2)
        label = f'{run.config.spec.origin.country} (origin)' if cid == 'origin' else f'{cid[6:]} countries'
        ev._add([{'id': f'cluster:{cid}', 'title': label, 'value': None, 'unit': '', 'year': None, 'source': 'World Bank WDI (population-weighted)',
                  'text': '; '.join(f'{k} {v}' for k, v in data.items())}])
        out.append({'id': cid, 'label': label, 'data': data})
    return out


def crowds(run, budget: llm.Budget | None = None, audit: list | None = None) -> Setup:
    """Stances per population cluster on the module's behavior dimensions, as labels. Code turns each label into a
    multiplier band (a prior), so the agent never sets a number."""
    role, dims = 'crowds', run.module.behavior_dims
    ev = Evidence(run.ctx.world, run.config.spec)
    cl = clusters(run, ev)
    labels = list(get_args(StanceLabel))
    schema = _obj({'stances': {'type': 'array', 'items': _obj({'cluster': {'type': 'string', 'enum': [c['id'] for c in cl]},
                                                                'stance': _obj({d: {'type': 'string', 'enum': labels} for d in dims}),
                                                                'rationale': STR, 'evidence': STRS})}})
    user = json.dumps({**scenario_brief(run), 'behaviors': dims, 'clusters': cl}, indent=1)
    out = run_role(role, user, schema, ev, budget, audit)
    if not out:
        return AgentStep(role=role, model=ROLES[role]['model'], status='failed', summary='No usable answer; typical behavior everywhere.'), None
    by_id, allowed, stances = {c['id']: c for c in cl}, user + ' ' + ev.text(), []
    for e in out.get('stances', []):
        c = by_id.pop(e['cluster'], None)  # one stance per cluster
        st = {d: v for d, v in (e.get('stance') or {}).items() if d in dims and v in labels}
        if c and st:
            stances.append(CrowdStance(cluster=c['id'], label=c['label'], stances=st, rationale=clean_text(e.get('rationale'), allowed),
                                       evidence=[i for i in e.get('evidence', []) if i in ev.seen]))
    shifted = sum(v != 'typical' for st in stances for v in st.stances.values())
    summary = f'Stances for {len(stances)} population cluster{"s" if len(stances) != 1 else ""}; {shifted} behavior{"s" if shifted != 1 else ""} differ from typical.'
    usd = audit[-1]['usd'] if audit else 0.0

    def apply(s: ScenarioSpec) -> None:
        s.behavior = stances

    return AgentStep(role=role, model=ROLES[role]['model'], status='done', summary=summary, usd=usd,
                     evidence=sorted({i for st in stances for i in st.evidence})), apply


SETUP: dict[str, Callable] = {'calibrator': calibrator, 'actors': actors, 'replan': replan, 'crowds': crowds}


def setup_roles(run) -> list[str]:
    """Agent roles that shape this run before the ensemble starts."""
    return ['calibrator'] + (['actors'] if run.module.policy_menu else []) + (['crowds'] if run.module.behavior_dims else [])


def run_setup(role: str, run, budget: llm.Budget | None, **kw) -> Setup:
    """Never raises: a crashed role is reported as failed and the run keeps the rule-based defaults."""
    audit: list[dict] = []
    try:
        return SETUP[role](run, budget, audit, **kw)
    except Exception as e:  # noqa: BLE001 - one role must not sink the run
        logging.getLogger('worldsim.agents').exception('setup role %s failed', role)
        return AgentStep(role=role, model=ROLES[role]['model'], status='failed', summary=f'{type(e).__name__}; the module defaults stand.'), None
    finally:
        run.audit.extend(audit)


CRITIC_KINDS = ['inconsistent', 'implausible_parameter', 'missing_mechanism']
CRITIC_SCHEMA = _obj({'flags': {'type': 'array', 'items': _obj({'kind': {'type': 'string', 'enum': CRITIC_KINDS}, 'text': STR})}})


def critic(run, facts: str, budget: llm.Budget | None = None, audit: list | None = None) -> list[dict]:
    """Judgment flags on a finished run (rule checks live in report.rule_flags). Flags only: it never changes a number."""
    if not llm.enabled():
        return []
    out = run_role('critic', facts, CRITIC_SCHEMA, Evidence(run.ctx.world), budget, audit)
    flags = []
    for f in (out or {}).get('flags', [])[:4]:
        text = clean_text(f.get('text'), facts)
        if text and f.get('kind') in CRITIC_KINDS:
            flags.append({'kind': f['kind'], 'text': text, 'generator': 'llm'})
    return flags


def validate_scale(out: dict, run, allowed: str) -> ScaleHypothesis:
    priors = {p.key for p in run.priors if p.high > p.low}
    bands = []
    for b in out.get('analog_bands', [])[:4]:
        aid = b['analog_id'].removeprefix('analog:')
        if analogs.get(aid):
            bands.append(AnalogBand(analog_id=aid, band=b['band'], why=clean_text(b.get('why'), allowed)))
    branches, taken = [], set()
    for b in out.get('branches', [])[:3]:
        tails = {}
        for t in b.get('tails', []):
            k = t['key'].removeprefix('prior:')
            if k in priors:
                tails[k] = PriorTail(key=k, side=t['side'])
        off = bool(b.get('disable_policies')) and bool(run.config.spec.policies)
        if not tails and not off:
            continue  # a path the engine cannot express is dropped, not guessed
        title = clean_text(b['title'], allowed) or 'Escalation path'
        branches.append(EscalationBranch(id=slug(title, taken), title=title, path=clean_text(b['path'], allowed), trigger=clean_text(b['trigger'], allowed),
                                         likelihood=b['likelihood'], tails=list(tails.values()), disable_policies=off))
    return ScaleHypothesis(reach_expected=out['reach_expected'], reach_why=clean_text(out.get('reach_why'), allowed), analog_bands=bands,
                           branches=branches, generator='llm')
