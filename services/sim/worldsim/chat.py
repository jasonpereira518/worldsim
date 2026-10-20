"""Follow-up intents on a finished run. Rule-based; every answer quotes the run's own logs and numbers."""
from __future__ import annotations

import re

from .parse import find_place, parse_interventions
from .util import fmt
from .world import world

ZOOM = re.compile(r'\b(zoom|go to|show me|fly to|look at|focus on)\b', re.I)
WHY = re.compile(r'\b(why|explain|how did|when did|what happened)\b', re.I)
BRANCH = re.compile(r'\b(what if|rerun|re-run|instead|suppose|branch)\b', re.I)
COMPARE = re.compile(r'\b(compare|versus|vs\.?|baseline|difference)\b', re.I)
FILTER = re.compile(r'\bshow only (companies|institutions|people|personas|flows)\b', re.I)
HELP = ('Try: "zoom into Brazil", "explain why Brazil was hit", "what if borders close on day 10", '
        '"rerun with a 20% lower price", "compare with the baseline", "show only companies", or /assumptions, /sources, /export.')


def explain(run, place) -> str:
    ctx = run.ctx
    iso3 = place.iso3
    events = [e for f in run.frames for e in f.events if place.country in e.title or place.country in e.places or place.name in e.places]
    lines = []
    for e in events[:5]:
        lines.append(f'{e.date} (day {e.t * ctx.dt}): {e.title}. Cause: {e.cause}.')
    last = run.traj.layers[-1] if run.traj.layers else {}
    for key, label, unit in run.module.layers[:2]:
        v = last.get(key, {}).get(iso3)
        if v is not None:
            lines.append(f'{label} at the end: {fmt(v)} {unit}.')
    c = ctx.c_idx.get(iso3)
    if c is not None and run.traj.p_status is not None:
        mask = ctx.p_c == c
        import numpy as np
        st = run.traj.p_status[-1][mask]
        pops = ctx.p_pop[mask]
        names = ['unaware', 'aware', 'reacting', 'affected', 'recovered', 'adopted', 'opposed']
        shares = {names[s]: pops[st == s].sum() / pops.sum() * 100 for s in np.unique(st)}
        lines.append('Population by final state: ' + ', '.join(f'{k} {v:.0f}%' for k, v in sorted(shares.items(), key=lambda kv: -kv[1])) + '.')
        country = ctx.world.countries.get(iso3)
        facts = []
        for k, label in run.module.explain_keys:
            v = country.ind.get(k) if country else None
            if v:
                facts.append(f'{label} {fmt(v.value)} ({v.source}, {v.year})')
        if facts:
            lines.append('Inputs that shaped it: ' + '; '.join(facts) + '.')
    if not lines:
        return f'{place.country} was not reached at a notable level in this run.'
    return '\n'.join(lines)


def handle_chat(run, message: str, t: int | None, create) -> dict:
    w = world()
    place = find_place(message, w)
    m = FILTER.search(message)
    if m:
        what = m.group(1).lower()
        layers = {'dots': what in ('people', 'personas'), 'institutions': what in ('companies', 'institutions'), 'flows': what == 'flows', 'bubbles': True}
        return {'reply': f'Showing only {what}.', 'action': {'type': 'layers', 'layers': layers}}
    if BRANCH.search(message) or parse_interventions(message):
        from .api import CreateRun
        cfg = create(CreateRun(prompt=message, parent_run_id=run.config.run_id, branch_at=t))
        ivs = cfg.spec.interventions[len(run.config.spec.interventions):]
        changes = '; '.join(f'{iv.kind.replace("_", " ")} on day {iv.day}' + (f' ({iv.value:+g})' if iv.value is not None else '') for iv in ivs) or 'edited assumptions'
        return {'reply': f'Branching from {run.config.run_id}: {changes}. Same seed, so differences come from the change.',
                'action': {'type': 'branch', 'run_id': cfg.run_id, 'spec': cfg.spec.model_dump(by_alias=True), 'parent_run_id': run.config.run_id}}
    if COMPARE.search(message):
        other = run.config.parent_run_id
        if not other:
            return {'reply': 'This run has no baseline yet. Ask a "what if" to branch it, then compare.'}
        return {'reply': 'Opening the comparison with the baseline run.', 'action': {'type': 'compare', 'a': other, 'b': run.config.run_id}}
    if WHY.search(message):
        if place:
            return {'reply': explain(run, place), 'action': {'type': 'zoom', 'center': [place.lon, place.lat], 'zoom': 5}}
        top = [e for f in run.frames for e in f.events if e.severity == 3][:6]
        chain = ' → '.join(n['label'] for n in run.traj.causal.get('nodes', [])[:6])
        return {'reply': '\n'.join(f'{e.date}: {e.title}. Cause: {e.cause}.' for e in top) + (f'\nMain chain: {chain}.' if chain else '')}
    if ZOOM.search(message) and place:
        return {'reply': f'Zooming to {place.name}, {place.country}.', 'action': {'type': 'zoom', 'center': [place.lon, place.lat], 'zoom': 6 if place.pop > 5e6 else 7}}
    return {'reply': HELP}
