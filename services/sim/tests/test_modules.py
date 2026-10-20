import numpy as np
import pytest

from worldsim.engine import central, execute, make_config, prepare
from worldsim.models import Intervention
from worldsim.modules.base import STATUS
from worldsim.modules.trade import resolve_parties
from worldsim.parse import parse_prompt
from worldsim.world import world

PROMPTS = {
    'epidemiology': 'A novel H5N1 variant begins human-to-human transmission in Vietnam',
    'disaster': 'A magnitude 8.1 quake hits Istanbul',
    'trade': 'The EU imposes a 40% tariff on Chinese EVs',
    'generic': 'Mass protests erupt in Lagos over fuel prices',
}


def build(module, seed=3, **over):
    spec = parse_prompt(PROMPTS[module], world())
    assert spec.module == module
    if 'horizon' in over:
        spec.horizon_days = over.pop('horizon')
    r = prepare(make_config(spec, seed, f'{module}_{seed}', 'fixture'))
    return r


def key_final(r, seed=0, interventions=None, **params):
    saved = r.ctx.spec.interventions
    if interventions:
        r.ctx.spec.interventions = saved + interventions
    try:
        return r.module.simulate(r.ctx, {**central(r.priors), **params}, np.random.default_rng(seed), False).key[-1]
    finally:
        r.ctx.spec.interventions = saved


@pytest.mark.parametrize('module', list(PROMPTS))
def test_module_contract(module):
    r = build(module, horizon=60 if module == 'epidemiology' else None) if module == 'epidemiology' else build(module)
    execute(r)
    tr = r.traj
    T = r.ctx.steps
    assert tr.p_status.shape == (T + 1, r.ctx.P) and len(tr.layers) == T + 1 and len(tr.flows) == T + 1
    for key, _, _ in r.module.layers:
        assert any(key in l for l in tr.layers), key
    for m in r.summary.metrics:
        assert m.low <= m.low50 <= m.value <= m.high50 <= m.high, m.name
    assert np.all(np.diff(tr.key) >= -1e-9)  # cumulative key metric never decreases
    st = tr.p_status.astype(int)
    back = np.diff(st, axis=0) < 0
    # only allowed backward moves: none; recovered (4) follows affected (3); opposed→adopted handled in launch only
    assert not back.any()
    assert r.report['confidence']['overall'] in ('low', 'medium', 'high')
    again = build(module, horizon=60 if module == 'epidemiology' else None) if module == 'epidemiology' else build(module)
    execute(again)
    assert [m.value for m in again.summary.metrics] == [m.value for m in r.summary.metrics]


def test_epidemiology_interventions_reduce_deaths():
    r = build('epidemiology', horizon=150)
    base = np.median([key_final(r, s) for s in range(3)])
    closed = np.median([key_final(r, s, [Intervention(kind='border_closure', day=5, text='close')]) for s in range(3)])
    severe = np.median([key_final(r, s, severity=3.0) for s in range(3)])
    assert closed <= base
    assert severe > base


def test_earthquake_gradient_and_retrofit():
    r = build('disaster')
    execute(r)
    st = r.traj.p_status[1]
    city = np.array([p.city for p in r.ctx.pop.people])
    assert (st[city == 'Istanbul'] == STATUS['affected']).all()
    assert (st[city == 'Tokyo'] < STATUS['reacting']).all()
    base = key_final(r)
    assert key_final(r, theta_rich=15.4) < base  # retrofit lowers deaths
    assert key_final(r, magnitude=7.0) < base


def test_trade_parties_and_mechanics():
    r = build('trade')
    importers, exporter, product = resolve_parties(r.ctx)
    assert r.ctx.iso3[exporter] == 'CHN' and product[0] == 'electric vehicles'
    assert {'DEU', 'FRA', 'BEL'} <= {r.ctx.iso3[c] for c in importers}
    tr = r.module.simulate(r.ctx, central(r.priors), np.random.default_rng(0), False)
    p = central(r.priors)
    assert tr.outcomes['price_change_pct'] == pytest.approx(p['tariff_pct'] * p['passthrough'])
    assert key_final(r, tariff_pct=20) < key_final(r, tariff_pct=40)


def test_generic_is_flagged_low_confidence():
    r = build('generic')
    execute(r)
    assert r.report['confidence']['overall'] == 'low'
    assert any('generic fallback' in x for x in r.report['confidence']['reasons'])
    assert r.summary.metrics[0].value < 0.2 * sum(p.pop for p in r.ctx.pop.people)  # a city protest stays local
