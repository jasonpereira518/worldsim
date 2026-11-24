"""Scale measurement: reach classes, magnitude bands, escalation-path sizing. Deterministic, LLM off."""
from types import SimpleNamespace

import numpy as np
import pytest

from worldsim import scale
from worldsim.engine import execute, make_config, prepare
from worldsim.modules.base import Prior
from worldsim.parse import parse_prompt
from worldsim.world import world


def fake_ctx(n_countries=30, locs_per_country=2, continents=('Asia', 'Europe', 'Africa')):
    iso3 = [f'C{i:02d}' for i in range(n_countries)]
    countries = {c: SimpleNamespace(continent=continents[i % len(continents)]) for i, c in enumerate(iso3)}
    loc_c = np.repeat(np.arange(n_countries), locs_per_country)
    return SimpleNamespace(C=n_countries, iso3=iso3, loc_c=loc_c, c_pop=np.full(n_countries, 1e6), world=SimpleNamespace(countries=countries))


def test_reach_classes():
    ctx = fake_ctx()
    a = np.zeros(len(ctx.loc_c))
    assert scale.reach_class(ctx, a) == ('local', 0)
    a[0] = 5000                                   # one place in one country
    assert scale.reach_class(ctx, a) == ('local', 1)
    a[1] = 5000                                   # two places, 1% of the country
    assert scale.reach_class(ctx, a)[0] == 'regional'
    a[1] = 300_000                                # 30.5% of the country
    assert scale.reach_class(ctx, a)[0] == 'national'
    a[2] = 1000                                   # a second country
    assert scale.reach_class(ctx, a) == ('multi_country', 2)
    a[::2] = 1000                                 # every country, three continents
    assert scale.reach_class(ctx, a) == ('global', 30)
    one_continent = fake_ctx(continents=('Europe',))
    assert scale.reach_class(one_continent, a)[0] == 'multi_country'  # 25+ countries on one continent is not global
    a[:] = 40                                     # 80 per country: below the 100-people floor everywhere
    assert scale.reach_class(ctx, a)[0] == 'local'


def test_reach_counts_places_inside_a_residual_location():
    # A "Rest of <country>" location holds several provinces; a module that resolves them reports places per country,
    # so damage across provinces is regional even though it lands in one model location.
    ctx = fake_ctx()
    a = np.zeros(len(ctx.loc_c))
    a[0] = 50_000
    places = np.zeros(ctx.C, int)
    assert scale.reach_class(ctx, a, places)[0] == 'local'
    places[0] = 3
    assert scale.reach_class(ctx, a, places)[0] == 'regional'  # the real-snapshot case is in test_scale_eval (Kumamoto)


def test_quantile_matches_triangular():
    p = Prior('x', 'x', 2.0, 1.0, 5.0)
    assert p.quantile(0) == pytest.approx(1.0) and p.quantile(1) == pytest.approx(5.0)
    assert p.quantile(0.25) == pytest.approx(2.0)  # mode sits at F = (2-1)/(5-1) = 0.25
    draws = np.array([p.sample(np.random.default_rng(i)) for i in range(4000)])
    assert np.median(draws) == pytest.approx(p.quantile(0.5), abs=0.08)
    assert Prior('y', 'y', 3.0, 3.0, 3.0).quantile(0.9) == 3.0


def test_bands():
    assert [scale.band(r) for r in (0.05, 0.2, 1.0, 5.0, 50.0)] == ['far below', 'below', 'comparable', 'above', 'far above']


@pytest.fixture(scope='module')
def quake():
    spec = parse_prompt('A magnitude 8.1 quake hits Istanbul', world())
    run = prepare(make_config(spec, 20261020, 'scale_q', 'fixture'))
    execute(run)
    return run


def test_measure_and_branches(quake):
    s = quake.scale
    dist = s['measurement']['reach']['distribution']
    assert set(dist) == set(scale.REACH) and sum(dist.values()) == pytest.approx(1.0)
    assert s['measurement']['reach']['mode'] in scale.REACH
    mags = s['measurement']['magnitude']
    assert mags and all(m['metric'] == 'deaths' and m['band'] in [b for _, b in scale.BANDS] for m in mags)
    assert {'izmit1999', 'kahramanmaras2023'} <= {m['analog_id'] for m in mags}
    assert s['measurement']['position'].startswith('Median deaths')
    ids = [b['id'] for b in s['branches']]
    assert ids == ['escalation', 'containment']
    up, down = s['branches']
    assert up['size']['p50'] >= down['size']['p50']
    for b in s['branches']:
        ex = b['exceedance']
        assert 0 <= ex['k'] <= ex['n'] == len(quake.ensemble)
        assert b['computed_likelihood'] in ('unlikely', 'possible', 'likely')
        assert sum(b['reach'].values()) == pytest.approx(1.0)
    # sizing is deterministic and paired with the base members
    again = scale.size_branches(quake, scale.default_branches(quake))
    assert [b['size'] for b in again] == [b['size'] for b in s['branches']]


def test_untouched_branch_reproduces_base_members(quake):
    """A branch with no tails re-runs exactly the base members (same parameter and simulation seeds)."""
    b = scale.size_branches(quake, [{'id': 'same', 'title': 't', 'path': 'p', 'trigger': 'x', 'tails': []}], n=len(quake.ensemble))[0]
    base = [tr.outcomes['deaths'] for tr in quake.ensemble]
    assert b['size']['p50'] == pytest.approx(float(np.percentile(base, 50)))


def test_report_section(quake):
    from worldsim.report import to_markdown
    md = to_markdown(quake.report)
    assert '## 2. Scale and plausibility' in md and 'Reach, measured across the ensemble' in md and 'Escalation paths' in md
