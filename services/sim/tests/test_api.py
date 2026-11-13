import json

from fastapi.testclient import TestClient

from worldsim.api import app

c = TestClient(app)


def events(run_id):
    out = []
    with c.stream('GET', f'/runs/{run_id}/stream') as s:
        kind = None
        for line in s.iter_lines():
            if line.startswith('event: '):
                kind = line[7:]
            elif line.startswith('data: '):
                out.append((kind, json.loads(line[6:])))
    return out


def test_sse_contract_and_report():
    r = c.post('/runs', json={'prompt': 'Apple launches a $499 AR headset worldwide on Dec 1, 2026'})
    assert r.status_code == 201
    rid = r.json()['run_id']
    ev = events(rid)
    kinds = [k for k, _ in ev]
    assert kinds[0] == 'personas' and kinds[-1] == 'done'
    assert kinds.index('summary') > max(i for i, k in enumerate(kinds) if k == 'frame')
    assert 'report' in kinds and 'error' not in kinds
    frame = next(d['frame'] for k, d in ev if k == 'frame')
    assert set(frame) >= {'t', 'date', 'deltas', 'bubbles', 'events', 'flows', 'metrics', 'layers', 'band'}
    md = c.get(f'/runs/{rid}/report.md').text
    for n in range(1, 13):
        assert f'## {n}. ' in md
    # replay serves the same frames without recomputing
    again = [d for k, d in events(rid) if k == 'frame']
    assert again == [d for k, d in ev if k == 'frame']


def test_branch_compare_and_chat():
    rid = c.post('/runs', json={'prompt': 'Apple launches a $499 AR headset worldwide on Dec 1, 2026'}).json()['run_id']
    br = c.post(f'/runs/{rid}/chat', json={'message': 'Rerun with a 20% lower price', 't': 5}).json()
    assert br['action']['type'] == 'branch'
    child = br['action']['run_id']
    cfg = c.get(f'/runs/{child}').json()
    parent = c.get(f'/runs/{rid}').json()
    assert cfg['seed'] == parent['seed'] and cfg['parent_run_id'] == rid
    assert abs(cfg['overrides']['price_usd'] - 399.2) < 1e-6
    cmp = c.get(f'/runs/{rid}/compare/{child}').json()
    units = next(m for m in cmp['metrics'] if m['name'] == 'Units shipped')
    assert units['b'] > units['a']
    z = c.post(f'/runs/{rid}/chat', json={'message': 'zoom into Japan'}).json()
    assert z['action']['type'] == 'zoom'
    ex = c.post(f'/runs/{rid}/chat', json={'message': 'explain why Japan adopted'}).json()
    assert 'test fixture' in ex['reply']  # cites the data it used
    assert c.post(f'/runs/{rid}/chat', json={'message': 'show only companies'}).json()['action']['layers']['institutions'] is True


def test_validation_and_unknown_run():
    assert c.post('/runs', json={'prompt': ''}).status_code == 422
    assert c.get('/runs/run_doesnotexist/stream').status_code == 404
    assert c.get('/runs/..%2Fetc/stream').status_code == 404


def test_concurrent_report_requests_run_the_pipeline_once():
    from concurrent.futures import ThreadPoolExecutor
    from fastapi.testclient import TestClient
    from worldsim import api
    c = TestClient(api.app)
    rid = c.post('/runs', json={'prompt': 'A magnitude 7.0 earthquake hits Port-au-Prince, Haiti'}).json()['run_id']
    with ThreadPoolExecutor(2) as ex:
        reports = list(ex.map(lambda _: c.get(f'/runs/{rid}/report').json(), range(2)))
    assert [r['appendix']['run']['ensemble_size'] for r in reports] == [api.ENSEMBLE, api.ENSEMBLE]
