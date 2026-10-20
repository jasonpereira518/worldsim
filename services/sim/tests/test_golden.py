"""Golden runs: fixed seed + fixture snapshot → stored ensemble outcomes. A change to any number must be deliberate.
Regenerate after an intended model change with: WORLDSIM_UPDATE_GOLDEN=1 pytest tests/test_golden.py"""
import json
import os
from pathlib import Path

import pytest

from worldsim.engine import execute, make_config, prepare
from worldsim.parse import parse_prompt
from worldsim.world import world

GOLDEN = Path(__file__).parent / 'golden'
CASES = {
    'launch': ('Apple launches a $499 AR headset worldwide on Dec 1, 2026', None),
    'outbreak': ('A novel H5N1 variant begins human-to-human transmission in Vietnam', 90),
    'quake': ('A magnitude 8.1 quake hits Istanbul', None),
    'tariff': ('The EU imposes a 40% tariff on Chinese EVs', None),
    'protest': ('Mass protests erupt in Lagos over fuel prices', None),
}


def snapshot(prompt: str, horizon: int | None) -> dict:
    spec = parse_prompt(prompt, world())
    if horizon:
        spec.horizon_days = horizon
    run = prepare(make_config(spec, 20261020, 'golden', 'fixture'))
    execute(run)
    return {'module': spec.module, 'ensemble': len(run.ensemble), 'median_member': run.median,
            'metrics': {m.name: [m.low, m.low50, m.value, m.high50, m.high] for m in run.summary.metrics},
            'events': [e.title for f in run.frames for e in f.events][:20],
            'bubbles': sum(len(f.bubbles) for f in run.frames)}


@pytest.mark.parametrize('case', list(CASES))
def test_golden(case):
    got = snapshot(*CASES[case])
    f = GOLDEN / f'{case}.json'
    if os.environ.get('WORLDSIM_UPDATE_GOLDEN') or not f.exists():
        f.write_text(json.dumps(got, indent=1, ensure_ascii=False) + '\n')
        if not os.environ.get('WORLDSIM_UPDATE_GOLDEN'):
            pytest.skip(f'wrote new golden file {f.name}; commit it')
    want = json.loads(f.read_text())
    assert got['module'] == want['module'] and got['median_member'] == want['median_member']
    assert got['events'] == want['events']
    assert got['bubbles'] == want['bubbles']
    assert set(got['metrics']) == set(want['metrics'])
    for k, vals in want['metrics'].items():
        assert got['metrics'][k] == pytest.approx(vals, rel=1e-6, abs=1e-9), k
