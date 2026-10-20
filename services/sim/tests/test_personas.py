import math

import pytest

from worldsim.personas import build_population, quantile_mean, share_above, sigma_from_gini
from worldsim.world import world


def test_lognormal_helpers_are_consistent():
    s = sigma_from_gini(40)
    # Gini of a lognormal: 2Φ(σ/√2) − 1
    assert 2 * 0.5 * (1 + math.erf(s / 2)) - 1 == pytest.approx(0.40, abs=1e-6)
    # the three worker slices average back to the mean
    m = 0.5 * quantile_mean(10000, s, 0, 0.5) + 0.4 * quantile_mean(10000, s, 0.5, 0.9) + 0.1 * quantile_mean(10000, s, 0.9, 1)
    assert m == pytest.approx(10000, rel=1e-9)
    assert share_above(10000, s, 1e9) == pytest.approx(0, abs=1e-6)
    assert share_above(10000, s, 1) == pytest.approx(1, abs=1e-6)
    assert share_above(10000, s, 20000, 0.9, 1.0) > share_above(10000, s, 20000, 0.0, 0.5)


def test_population_conserves_world_bank_totals():
    w = world()
    pop = build_population(w)
    by_c = {}
    for p in pop.people:
        by_c[p.iso3] = by_c.get(p.iso3, 0) + p.pop
    for iso3, c in w.countries.items():
        if c.population:
            assert by_c[iso3] == pytest.approx(c.population, rel=1e-6), iso3
    assert len({p.id for p in pop.people}) == len(pop.people)


def test_traits_follow_data():
    pop = build_population(world())
    def avg(iso3, key, seg):
        xs = [p.traits[key] for p in pop.people if p.iso3 == iso3 and p.segment == seg]
        return sum(xs) / len(xs)
    assert avg('KOR', 'tech_adoption', 'workers_mid') > avg('NGA', 'tech_adoption', 'workers_mid')
    assert avg('NGA', 'price_sensitivity', 'workers_low') > avg('USA', 'price_sensitivity', 'workers_high')
    assert avg('JPN', 'tech_adoption', 'seniors') < avg('JPN', 'tech_adoption', 'workers_high')
