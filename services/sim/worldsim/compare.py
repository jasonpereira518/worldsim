"""Side-by-side comparison of two finished runs."""
from __future__ import annotations


def compare_runs(a, b) -> dict:
    ma = {m.name: m for m in a.summary.metrics}
    rows = []
    for m in b.summary.metrics:
        o = ma.get(m.name)
        if o is None:
            continue
        rows.append({'name': m.name, 'unit': m.unit, 'a': o.value, 'a_low': o.low, 'a_high': o.high, 'b': m.value, 'b_low': m.low, 'b_high': m.high,
                     'delta': m.value - o.value, 'delta_pct': (m.value - o.value) / o.value * 100 if o.value else None})
    key = a.module.layers[0][0] if a.module.layers else None
    la = a.traj.layers[-1].get(key, {}) if key and a.traj.layers else {}
    lb = b.traj.layers[-1].get(key, {}) if key and b.traj.layers else {}
    # countries above 5M people only: per-capita layers in microstates are dominated by run-to-run noise
    big = {c for c in set(la) | set(lb) if c in a.ctx.c_idx and a.ctx.c_pop[a.ctx.c_idx[c]] >= 5e6}
    deltas = sorted(((c, lb.get(c, 0) - la.get(c, 0)) for c in big), key=lambda kv: -abs(kv[1]))[:10]
    return {
        'a': {'run_id': a.config.run_id, 'title': a.config.spec.title, 'label': a.config.label, 'interventions': [i.model_dump() for i in a.config.spec.interventions]},
        'b': {'run_id': b.config.run_id, 'title': b.config.spec.title, 'label': b.config.label, 'interventions': [i.model_dump() for i in b.config.spec.interventions]},
        'metrics': rows,
        'series': {'unit': a.module.key_unit, 'dates': [f.date for f in a.frames], 'a': [f.band for f in a.frames], 'b': [f.band for f in b.frames]},
        'layer': {'key': key, 'label': a.module.layers[0][1] if key else '', 'deltas': [{'iso3': c, 'country': a.ctx.c_name[a.ctx.c_idx[c]] if c in a.ctx.c_idx else c,
                                                                                  'delta': d} for c, d in deltas]},
    }
