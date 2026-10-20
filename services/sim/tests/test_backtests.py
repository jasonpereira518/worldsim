"""Backtests against historical events. Run against the real data snapshot (skipped when it is not present)."""
import math
from pathlib import Path

import numpy as np
import pytest

from worldsim.engine import central, make_config, prepare
from worldsim.models import Place
from worldsim.parse import parse_prompt
from worldsim.world import ROOT, load_world

SNAP = ROOT / 'data' / 'snapshots'
REAL = SNAP / (SNAP / 'LATEST').read_text().strip() if (SNAP / 'LATEST').exists() else None
pytestmark = pytest.mark.skipif(REAL is None or not (REAL / 'admin1.parquet').exists(), reason='real data snapshot not present')

# name, lat, lon, Mw, depth km, recorded deaths, source of the record
EARTHQUAKES = [
    ('1999 Izmit', 40.75, 29.86, 7.6, 17, 17127, 'Turkish government via USGS'),
    ('2023 Kahramanmaraş', 37.17, 37.03, 7.8, 10, 50783, 'AFAD, Türkiye only'),
    ('2015 Gorkha', 28.23, 84.73, 7.8, 8, 8964, 'Government of Nepal'),
    ('2010 Haiti', 18.46, -72.53, 7.0, 13, 160000, 'Kolbe et al. (2010) household survey'),
    ('2016 Kumamoto', 32.79, 130.75, 7.0, 10, 273, 'Japan Cabinet Office, incl. related deaths'),
    ('2008 Wenchuan', 31.0, 103.4, 7.9, 19, 87587, 'Government of China, dead and missing'),
]


def simulate(w, lat, lon, mag, depth, **over):
    spec = parse_prompt(f'A magnitude {mag} earthquake hits', w, {'origin': 'Tokyo'})
    spec.origin = Place(id=-1, name='epicenter', country='', iso3='', iso2='', admin1='', lat=lat, lon=lon, pop=0, capital=False, hub=False)
    spec.horizon_days = 14
    run = prepare(make_config(spec, 1, 'bt', w.snapshot_id), w=w)
    p = {**central(run.priors), 'depth_km': depth, **over}
    return float(np.median([run.module.simulate(run.ctx, p, np.random.default_rng(i), False).outcomes['deaths'] for i in range(3)]))


def test_earthquake_fatalities_backtest():
    w = load_world(REAL)
    logs, inside = [], 0
    for name, lat, lon, mag, depth, obs, _ in EARTHQUAKES:
        sim = simulate(w, lat, lon, mag, depth)
        lo = simulate(w, lat, lon, mag, depth, theta_rich=15.2, beta=0.14)
        hi = simulate(w, lat, lon, mag, depth, theta_rich=13.6, beta=0.24)
        logs.append(math.log10(max(sim, 1) / obs))
        inside += lo <= obs <= hi
    bias = 10 ** np.mean(logs)
    assert 1 / 3 <= bias <= 3, f'geometric-mean bias {bias:.2f}'
    assert sum(abs(x) <= math.log10(5) for x in logs) >= 5  # within 5× for five of six
    assert inside >= 5  # the record sits inside the prior-swept range
