import numpy as np

from worldsim.engine import execute, make_config, prepare
from worldsim.modules.base import STATUS
from worldsim.parse import parse_prompt
from worldsim.voices import numbers_ok
from worldsim.world import world

PROMPT = 'Apple launches a $499 AR headset worldwide on Dec 1, 2026'


def run(seed=7, overrides=None, prompt=PROMPT):
    spec = parse_prompt(prompt, world())
    r = prepare(make_config(spec, seed, f'test_{seed}', 'fixture'), overrides)
    execute(r)
    return r


def test_end_to_end_with_ranges_and_report():
    r = run()
    units = r.summary.metrics[0]
    assert units.name == 'Units shipped' and units.low <= units.low50 <= units.value <= units.high50 <= units.high
    assert units.high > units.low  # visibly uncertain, never a point estimate
    assert len(r.frames) == r.ctx.steps + 1
    assert all(f.band and len(f.band) == 5 for f in r.frames)
    rep = r.report
    for k in ('headline', 'key_outcomes', 'timeline', 'geography', 'winners_losers', 'voices', 'causal', 'sensitivities', 'decision_points', 'confidence', 'appendix'):
        assert rep[k] is not None, k
    n_events = len([e for f in r.frames for e in f.events])
    assert len(rep['timeline']) == min(15, n_events) if n_events <= 8 else 8 <= len(rep['timeline']) <= 15
    assert len(rep['sensitivities']) == 5
    assert rep['confidence']['overall'] in ('high', 'medium', 'low')
    assert any(a['id'] == 'bass_p' and a['source'] for a in rep['appendix']['assumptions'])


def test_reproducible_from_seed_and_config():
    a, b = run(seed=11), run(seed=11)
    assert [m.value for m in a.summary.metrics] == [m.value for m in b.summary.metrics]
    assert [f.model_dump() for f in a.frames] == [f.model_dump() for f in b.frames]
    c = run(seed=12)
    assert [m.value for m in c.summary.metrics] != [m.value for m in a.summary.metrics]


def test_rollout_waves_and_price_response():
    r = run()
    lay = r.traj.layers
    launch_t = next(e['t'] for e in r.traj.events if e['title'].startswith('Launch'))
    on_sale = lay[launch_t]['available']
    assert 'USA' in on_sale and 'JPN' in on_sale
    assert 'CHN' not in on_sale and 'VNM' not in on_sale and 'DEU' not in on_sale  # later waves / EU review
    base = r.module.simulate(r.ctx, {p.key: p.value for p in r.priors}, np.random.default_rng(0), False).key[-1]
    cheaper = r.module.simulate(r.ctx, {**{p.key: p.value for p in r.priors}, 'price_usd': 299}, np.random.default_rng(0), False).key[-1]
    assert cheaper > base


def test_status_rules_and_bubbles_trace_to_numbers():
    r = run()
    st = r.traj.p_status
    adopted = st[-1] == STATUS['adopted']
    assert adopted.any()
    assert not (np.diff(st.astype(int), axis=0)[:, adopted] < 0).any()  # adopters never revert
    seen = 0
    for f in r.frames:
        for b in f.bubbles:
            assert len(b.text) <= 140
            assert b.why.metric and b.why.unit
            seen += 1
    assert seen > 20


def test_user_override_fixes_prior():
    r = run(overrides={'capacity_max_k': 250})
    p = next(p for p in r.priors if p.key == 'capacity_max_k')
    assert p.low == p.high == p.value == 250
    assert all(params['capacity_max_k'] == 250 for params in r.params)


def test_numbers_ok():
    assert numbers_ok('12.5 cases per 100k', 'cases 3 → 12.5 per 100k')
    assert not numbers_ok('40% of us', 'cases 3 → 12.5')
