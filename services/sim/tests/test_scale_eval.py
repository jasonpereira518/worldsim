"""Scale evaluation: historical events phrased as prompts (evals/scale_cases.jsonl), run end to end on the real snapshot
and scored against the analog library: reach class vs the event's recorded reach, and the headline outcome within a
factor of ten of the recorded one. The floors are today's scores, so a change that makes scale judgments worse fails.
Run with -s for the table. WORLDSIM_LIVE_EVAL=1 with WORLDSIM_LLM=on also scores the scale assessor (costs money)."""
import json
import os
from pathlib import Path

import pytest

from worldsim import analogs, llm, scale
from worldsim.engine import make_config, prepare, run_ensemble
from worldsim.parse import parse_prompt
from worldsim.world import ROOT, load_world

SNAP = ROOT / 'data' / 'snapshots'
REAL = SNAP / (SNAP / 'LATEST').read_text().strip() if (SNAP / 'LATEST').exists() else None
pytestmark = pytest.mark.skipif(REAL is None or not (REAL / 'admin1.parquet').exists(), reason='real data snapshot not present')
CASES = [json.loads(l) for l in (Path(__file__).resolve().parents[1] / 'evals' / 'scale_cases.jsonl').read_text().splitlines() if l.strip()]
WITHIN_10X = ('below', 'comparable', 'above')
# 2026-10-24 baseline on snapshot 2026-10-23: reach 8/11, magnitude 6/10. Misses: Kahramanmaras and Gorkha stay
# regional (recorded multi-country); the gazetteer lacks Izmit, Kahramanmaras and Kumamoto (origin falls back to the
# capital); novel-pathogen defaults land far above H1N1 and SARS.
REACH_FLOOR, BAND_FLOOR = 7, 5


def evaluate(w, case, assessor=False):
    spec = parse_prompt(case['prompt'], w, case.get('answers'))
    run = prepare(make_config(spec, 1, f'eval_{case["id"]}', w.snapshot_id), w=w)
    run_ensemble(run, n=8)
    m, a = scale.measure(run), analogs.get(case['analog'])
    band = next((x['band'] for x in m['magnitude'] if x['analog_id'] == case['analog'] and x['metric'] == m['headline_metric']), None)
    row = {'id': case['id'], 'origin': spec.origin.name if spec.origin else None, 'reach': m['reach']['mode'], 'expected': a['reach'], 'band': band}
    if assessor:
        from worldsim.agents import scale_assessor
        hyp = scale_assessor(run, llm.Budget(max_usd=0.25))
        row['forecast'] = hyp.reach_expected if hyp else None
    return row


def test_scale_eval_meets_floor():
    w = load_world(REAL)
    rows = [evaluate(w, c) for c in CASES]
    for r in rows:
        print(f"{r['id']:18} origin={r['origin'] or '-':15} reach={r['reach']:13} expected={r['expected']:13} band={r['band']}")
    reach_hits = sum(r['reach'] == r['expected'] for r in rows)
    banded = [r for r in rows if r['band']]
    band_hits = sum(r['band'] in WITHIN_10X for r in banded)
    print(f'reach {reach_hits}/{len(rows)}, magnitude within 10x {band_hits}/{len(banded)}')
    assert reach_hits >= REACH_FLOOR and band_hits >= BAND_FLOOR


@pytest.mark.skipif(os.environ.get('WORLDSIM_LIVE_EVAL') != '1', reason='live eval spends API money; set WORLDSIM_LIVE_EVAL=1')
def test_scale_assessor_live(monkeypatch):
    monkeypatch.setenv('WORLDSIM_LLM', 'on')
    w = load_world(REAL)
    rows = [evaluate(w, c, assessor=True) for c in CASES]
    hits = sum(r['forecast'] == r['expected'] for r in rows)
    print(f'assessor reach forecasts: {hits}/{len(rows)} match the recorded reach; engine matched {sum(r["reach"] == r["expected"] for r in rows)}')
