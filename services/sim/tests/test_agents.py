"""Agents with a scripted fake client: the tool loop, budgets, validation, plausibility, and replay without API calls."""
import json
from collections import Counter
from types import SimpleNamespace

import pytest

from worldsim import agents, llm
from worldsim.engine import execute, make_config, prepare
from worldsim.parse import parse_prompt
from worldsim.world import world


def usage(i=1000, o=200, cache_read=0, cache_write=0):
    return SimpleNamespace(input_tokens=i, output_tokens=o, cache_read_input_tokens=cache_read, cache_creation_input_tokens=cache_write)


def final(obj, **u):
    return SimpleNamespace(stop_reason='end_turn', usage=usage(**u), content=[SimpleNamespace(type='text', text=json.dumps(obj))])


def tool_call(name, args, call_id='t1'):
    return SimpleNamespace(stop_reason='tool_use', usage=usage(),
                           content=[SimpleNamespace(type='tool_use', id=call_id, name=name, input=args)])


REFUSAL = SimpleNamespace(stop_reason='refusal', usage=usage(100, 0), content=[])


class Router:
    """Plays a script per role, chosen by a phrase in the system prompt; anything else is refused (deterministic path)."""
    def __init__(self, scripts: dict[str, list]):
        self.scripts = {k: list(v) for k, v in scripts.items()}
        self.calls, self.kwargs, self.by_role = 0, [], Counter()
        self.messages = self
        self.beta = SimpleNamespace(messages=self)

    def create(self, **kw):
        self.calls += 1
        self.kwargs.append(kw)
        assert kw['output_config']['format']['type'] == 'json_schema'
        assert kw.get('tool_choice', {'type': 'auto'})['type'] in ('auto', 'none')  # forcing a tool is a 400 on Opus/Sonnet 5.5
        for phrase, script in self.scripts.items():
            if phrase in kw['system']:
                self.by_role[phrase] += 1
                return script.pop(0) if len(script) > 1 else script[0]
        return REFUSAL


@pytest.fixture
def llm_on(monkeypatch, tmp_path):
    monkeypatch.setenv('WORLDSIM_LLM', 'on')
    monkeypatch.setattr(llm, 'CACHE_DIR', tmp_path / 'llm')

    def install(scripts):
        fake = Router(scripts)
        monkeypatch.setattr(llm, '_client', fake)
        return fake
    return install


def test_agent_loop_runs_tools_and_forces_an_answer(llm_on):
    fake = llm_on({'S': [tool_call('echo', {'x': 'a'}), tool_call('echo', {'x': 'b'}, 't2'), final({'done': True})]})
    seen = []
    tools = [{'name': 'echo', 'description': 'd', 'input_schema': {'type': 'object'}, 'fn': lambda x: seen.append(x) or {'got': x}}]
    b = llm.Budget()
    out = llm.agent('S', 'u', {'type': 'object'}, tools, budget=b, max_turns=3)
    assert out == {'done': True} and seen == ['a', 'b'] and fake.calls == 3
    last = fake.kwargs[-1]
    assert last['tool_choice'] == {'type': 'none'}  # last allowed turn must answer
    assert last['tools'][0]['strict'] is True and last['cache_control'] == {'type': 'ephemeral'}
    results = last['messages'][-1]['content']
    assert results[0]['type'] == 'tool_result' and json.loads(results[0]['content']) == {'got': 'b'}
    assert b.calls == 3


def test_tool_errors_go_back_to_the_model(llm_on):
    fake = llm_on({'S': [tool_call('boom', {}), final({'ok': 1})]})
    tools = [{'name': 'boom', 'description': 'd', 'input_schema': {'type': 'object'}, 'fn': lambda: 1 / 0}]
    assert llm.agent('S', 'u', {'type': 'object'}, tools) == {'ok': 1}
    assert fake.kwargs[-1]['messages'][-1]['content'][0]['is_error'] is True


def test_sub_budget_charges_parent_and_bills_cache_tokens(llm_on):
    llm_on({'S': [final({'a': 1}, i=0, o=0, cache_read=1_000_000, cache_write=1_000_000)]})
    run_b = llm.Budget(max_usd=1.0)
    role_b = run_b.child(0.5)
    llm.agent('S', 'u', {'type': 'object'}, model='claude-opus-5-5', budget=role_b)
    assert role_b.usd == pytest.approx(0.20 + 4.0 * 1.25) and run_b.usd == role_b.usd  # cache read $0.20/MTok, write 1.25× input
    assert not role_b.allow()                                                          # over its own cap
    assert not run_b.child(0.5).allow()                                                # parent over its cap blocks every child


def test_refusal_and_out_of_turns_return_none(llm_on):
    llm_on({'S': [REFUSAL]})
    b = llm.Budget()
    assert llm.agent('S', 'u', {'type': 'object'}, budget=b) is None and b.refusals == 1
    llm_on({'S': [tool_call('echo', {'x': 'a'})]})
    tools = [{'name': 'echo', 'description': 'd', 'input_schema': {'type': 'object'}, 'fn': lambda x: x}]
    assert llm.agent('S', 'u2', {'type': 'object'}, tools, max_turns=2) is None


INTAKE = {'event_type': 'disaster', 'origin_place': 'Istanbul', 'is_global': False, 'needs_clarification': False, 'clarifying_question': None,
          'actors': ['AFAD'], 'mechanisms': ['ground shaking', 'collapse of 40% of buildings'], 'title': 'M8.1 earthquake hits Istanbul',
          'plausibility': {'verdict': 'stretched', 'reasons': ['Magnitude 8.1 is near the upper end for the North Anatolian Fault.', 'It would kill 2 million people.'],
                           'adjusted_premise': None}, 'evidence': ['place:1']}


def test_intake_validated(llm_on):
    llm_on({'intake analyst': [final(INTAKE)]})
    spec = parse_prompt('A magnitude 8.1 quake hits Istanbul', world())
    assert spec.parser == 'llm' and spec.plausibility.verdict == 'stretched' and spec.plausibility.generator == 'llm'
    assert spec.plausibility.reasons == ['Magnitude 8.1 is near the upper end for the North Anatolian Fault.']  # invented "2 million" cut
    assert spec.mechanisms == ['ground shaking']  # invented "40%" cut
    assert spec.clarifying_question is None and spec.module == 'disaster'


def test_rules_plausibility_gate_without_llm():
    spec = parse_prompt('A magnitude 11 quake hits Istanbul', world())
    assert next(a.value for a in spec.assumptions if a.id == 'magnitude') == 11.0  # two-digit magnitudes parse
    assert spec.plausibility.verdict == 'impossible' and spec.plausibility.generator == 'rules'
    assert spec.clarifying_question.startswith('This premise looks impossible')
    assert parse_prompt('A magnitude 9.1 quake hits Tokyo', world()).plausibility.verdict == 'stretched'
    assert parse_prompt('A magnitude 7.1 quake hits Tokyo', world()).plausibility is None  # not judged without the agent


def test_physical_limit_outranks_the_agent(llm_on):
    llm_on({'intake analyst': [final({**INTAKE, 'plausibility': {'verdict': 'realistic', 'reasons': [], 'adjusted_premise': None}})]})
    assert parse_prompt('A magnitude 11 quake hits Istanbul', world()).plausibility.verdict == 'impossible'


SCALE = {'reach_expected': 'regional', 'reach_why': 'Shaking stays within the Marmara region. Deaths reach 300,000.',
         'analog_bands': [{'analog_id': 'analog:izmit1999', 'band': 'above', 'why': 'Larger magnitude under a bigger city.'},
                          {'analog_id': 'analog:atlantis', 'band': 'far above', 'why': 'not in the library'}],
         'branches': [{'title': 'Weak building stock', 'path': 'older housing fails', 'trigger': 'code enforcement was poor', 'likelihood': 'possible',
                       'tails': [{'key': 'prior:theta_rich', 'side': 'lower'}, {'key': 'made_up', 'side': 'upper'}]},
                      {'title': 'Untranslatable', 'path': 'x', 'trigger': 'y', 'likelihood': 'likely', 'tails': [{'key': 'nope', 'side': 'upper'}]}],
         'evidence': ['analog:izmit1999']}


def test_scale_assessor_validated(llm_on):
    llm_on({'scale assessor': [tool_call('list_priors', {}), final(SCALE)]})
    run = prepare(make_config(parse_prompt('A magnitude 8.1 quake hits Istanbul', world()), 1, 'sa', 'fixture'))
    audit = []
    hyp = agents.scale_assessor(run, llm.Budget(), audit)
    assert hyp.reach_expected == 'regional' and hyp.reach_why == 'Shaking stays within the Marmara region.'  # invented toll cut
    assert [b.analog_id for b in hyp.analog_bands] == ['izmit1999']                                       # unknown analog dropped
    assert len(hyp.branches) == 1 and [(t.key, t.side) for t in hyp.branches[0].tails] == [('theta_rich', 'lower')]
    assert audit[0]['role'] == 'scale' and audit[0]['ok'] and 'prior:theta_rich' in audit[0]['evidence']
    # the engine sizes the agent's branch and scores the forecast
    run.config.spec.scale = hyp
    execute(run)
    s = run.scale
    assert [b['id'] for b in s['branches']] == [hyp.branches[0].id] and s['branches'][0]['likelihood'] == 'possible'
    assert 'computed_likelihood' in s['branches'][0] and 'forecast' in s['measurement']


def test_stream_sends_scale_and_replays_without_calls(llm_on, monkeypatch):
    from fastapi.testclient import TestClient
    from worldsim import api
    monkeypatch.setattr(api, 'FRAME_DELAY', 0)
    fake = llm_on({'intake analyst': [final(INTAKE)], 'scale assessor': [final(SCALE)]})
    c = TestClient(api.app)
    rid = c.post('/runs', json={'prompt': 'A magnitude 8.1 quake hits Istanbul'}).json()['run_id']

    def scale_events():
        out = []
        with c.stream('GET', f'/runs/{rid}/stream') as s:
            kind = None
            for line in s.iter_lines():
                if line.startswith('event: '):
                    kind = line[7:]
                elif line.startswith('data: ') and kind == 'scale':
                    out.append(json.loads(line[6:])['scale'])
        return out

    first = scale_events()
    assert first[0]['plausibility']['verdict'] == 'stretched'
    assert first[-1]['hypothesis']['reach_expected'] == 'regional'
    saved = c.get(f'/runs/{rid}').json()['spec']
    assert saved['scale']['reach_expected'] == 'regional'
    lines = api.audit_path(rid).read_text().splitlines()
    roles_logged = [json.loads(l)['role'] for l in lines]  # setup roles finish in either order
    assert roles_logged[0] == 'intake' and sorted(roles_logged[1:3]) == ['actors', 'calibrator'] and roles_logged[3] == 'scale'
    roles = dict(fake.by_role)
    api.CACHE.clear()  # force a fresh prepare from the saved config
    again = scale_events()
    assert again[0]['hypothesis']['reach_expected'] == 'regional' and dict(fake.by_role) == roles  # forecast came from the spec


CALIBRATION = {'proposals': [
    {'key': 'prior:depth_km', 'value': 12.0, 'low': 10.0, 'high': 20.0, 'rationale': 'Marmara events are shallow crustal ruptures.', 'evidence': ['prior:depth_km']},
    {'key': 'intensity_offset', 'value': 9.0, 'low': -9.0, 'high': 9.0, 'rationale': 'Wider than allowed.', 'evidence': ['prior:intensity_offset']},
    {'key': 'beta', 'value': 0.2, 'low': None, 'high': None, 'rationale': 'No citation.', 'evidence': ['analog:not_retrieved']},
    {'key': 'magnitude', 'value': 7.0, 'low': None, 'high': None, 'rationale': 'The user set this.', 'evidence': ['prior:depth_km']},
    {'key': 'made_up', 'value': 1.0, 'low': None, 'high': None, 'rationale': 'Not a parameter.', 'evidence': ['prior:depth_km']},
]}


def test_cached_answer_keeps_its_evidence(llm_on):
    # a repeated prompt is answered from the disk cache; its tool lookups are replayed so cited values still validate
    fake = llm_on({'calibrator for Worldsim': [tool_call('list_priors', {}), final(CALIBRATION)]})
    steps = []
    for _ in range(2):
        run = prepare(make_config(parse_prompt('A magnitude 8.1 quake hits Istanbul', world()), 1, 'cal', 'fixture'))
        steps.append(agents.calibrator(run, llm.Budget(), [])[0])
    assert fake.by_role['calibrator for Worldsim'] == 2  # tool turn + answer, once: the second run made no calibrator call
    assert steps[1].summary == steps[0].summary and steps[1].summary.startswith('Set 2 parameters')


def test_calibrator_clamps_and_requires_evidence(llm_on):
    llm_on({'calibrator for Worldsim': [tool_call('list_priors', {}), final(CALIBRATION)]})
    from worldsim.engine import apply_llm_assumptions
    run = prepare(make_config(parse_prompt('A magnitude 8.1 quake hits Istanbul', world()), 1, 'cal', 'fixture'))
    audit = []
    step, apply = agents.calibrator(run, llm.Budget(), audit)
    assert step.status == 'done' and step.summary.startswith('Set 2 parameters') and 'discarded 3' in step.summary
    apply(run.config.spec)
    llm_rows = {a.id: a for a in run.config.spec.assumptions if a.origin == 'llm'}
    assert set(llm_rows) == {'depth_km', 'intensity_offset'}  # uncited, user-locked (magnitude) and unknown keys dropped
    att = llm_rows['intensity_offset']
    assert (att.low, att.high, att.value) == (-0.7, 0.7, 0.7)  # cannot widen the code range; value clamped into it
    apply_llm_assumptions(run.priors, run.config.spec, run.overrides)
    depth = next(p for p in run.priors if p.key == 'depth_km')
    assert (depth.value, depth.low, depth.high, depth.origin) == (12.0, 10.0, 20.0, 'llm') and depth.source.startswith('calibrator (AI)')
    assert next(p for p in run.priors if p.key == 'magnitude').origin == 'user'


def test_setup_step_streams_and_replays(llm_on, monkeypatch):
    from fastapi.testclient import TestClient
    from worldsim import api
    monkeypatch.setattr(api, 'FRAME_DELAY', 0)
    fake = llm_on({'calibrator for Worldsim': [tool_call('list_priors', {}), final(CALIBRATION)]})
    c = TestClient(api.app)
    rid = c.post('/runs', json={'prompt': 'A magnitude 8.1 quake hits Istanbul'}).json()['run_id']

    def stream():
        out = []
        with c.stream('GET', f'/runs/{rid}/stream') as s:
            kind = None
            for line in s.iter_lines():
                if line.startswith('event: '):
                    kind = line[7:]
                elif line.startswith('data: ') and kind in ('agent', 'spec', 'frame'):
                    out.append((kind, json.loads(line[6:])))
        return out

    ev = stream()
    kinds = [k for k, _ in ev]
    assert kinds.index('spec') < kinds.index('frame')  # setup finishes before the ensemble streams
    agent_events = [d['agent'] for k, d in ev if k == 'agent']
    assert [a['status'] for a in agent_events[:2]] == ['running', 'running']
    assert {a['role']: a['status'] for a in agent_events[2:]} == {'calibrator': 'done', 'actors': 'failed'}  # actors refused: no policies
    spec = next(d['spec'] for k, d in ev if k == 'spec')
    assert any(a['origin'] == 'llm' and a['id'] == 'depth_km' for a in spec['assumptions'])
    saved = json.loads((api.RUNS_DIR / f'{rid}.json').read_text())
    assert saved['agents']['setup_done'] and sorted(st['role'] for st in saved['agents']['steps']) == ['actors', 'calibrator']
    assert 'replan' not in saved['agents']  # nothing to revise without policies
    calls = fake.by_role['calibrator for Worldsim']
    api.CACHE.clear()
    again = [d['agent'] for k, d in stream() if k == 'agent']
    assert sorted(a['status'] for a in again) == ['done', 'failed'] and fake.by_role['calibrator for Worldsim'] == calls  # roster replayed, no call
    report = c.get(f'/runs/{rid}/report').json()
    assert any(a['id'] == 'depth_km' and a['origin'] == 'llm' for a in report['appendix']['assumptions'])


ACTORS = {'policies': [
    {'actor': 'AFAD and international partners', 'action': 'aid', 'scope': 'origin', 'threshold': 50.0, 'lag_days': 30.0, 'duration_days': 10.0,
     'rationale': 'Turkey requests international search teams quickly.', 'evidence': ['country:TUR', 'analog:not_retrieved']},
    {'actor': 'UN OCHA', 'action': 'aid', 'scope': 'all', 'threshold': 5.0, 'lag_days': 2.0, 'duration_days': None, 'rationale': 'Same action again.', 'evidence': []},
    {'actor': 'Ministry of Health', 'action': 'lockdown', 'scope': 'origin', 'threshold': 5.0, 'lag_days': 2.0, 'duration_days': 30.0, 'rationale': 'Not on this menu.', 'evidence': []},
]}
REVISED = {'policies': [{**ACTORS['policies'][0], 'threshold': 20.0, 'lag_days': 10.0}]}
ACTORS_PHRASE = 'You decide for the actors'


def quake_run(rid='act'):
    return prepare(make_config(parse_prompt('A magnitude 8.1 quake hits Istanbul', world()), 1, rid, 'fixture'))


def test_actors_menu_scope_and_clamp(llm_on):
    llm_on({ACTORS_PHRASE: [tool_call('get_country', {'iso3': 'TUR'}), final(ACTORS)]})
    from worldsim.engine import refresh_priors
    run = quake_run()
    assert agents.setup_roles(run) == ['calibrator', 'actors']
    step, apply = agents.actors(run, llm.Budget(), [])
    assert step.status == 'done' and step.summary.startswith('1 conditional policy')
    apply(run.config.spec)
    [pol] = run.config.spec.policies  # duplicate (action, scope) and off-menu action dropped
    assert (pol.id, pol.scope, pol.evidence) == ('aid_all', 'all', ['country:TUR'])  # menu scope enforced; unretrieved evidence dropped
    vals = {a.id: a.value for a in run.config.spec.assumptions if a.id.startswith('pol_')}
    assert vals == {'pol_aid_all_threshold': 50.0, 'pol_aid_all_lag': 10.0}  # lag clamped into the menu range; aid has no duration
    refresh_priors(run)
    thr = next(p for p in run.priors if p.key == 'pol_aid_all_threshold')
    assert (thr.value, thr.low, thr.high, thr.origin) == (50.0, 10.0, 10000.0, 'llm')  # agent sets the center; the ensemble keeps the range
    execute(run)
    assert run.traj.decisions and run.traj.decisions[0]['policy'] == 'aid_all'
    d = run.report['decisions']
    assert d['policies'][0]['fired_runs'] == len(run.ensemble) and d['adaptation'] is None


def test_replan_round(llm_on):
    from worldsim.engine import quick_look, refresh_priors
    fake = llm_on({ACTORS_PHRASE: [final(ACTORS), final(REVISED)]})
    run = quake_run('rp')
    agents.actors(run, llm.Budget(), [])[1](run.config.spec)
    refresh_priors(run)
    look = quick_look(run, 4)
    assert look['n'] == 4 and look['fired']['aid_all']['runs'] == 4
    step, apply = agents.replan(run, llm.Budget(), [], look=look)
    assert 'first_look' in fake.kwargs[-1]['messages'][0]['content'] and step.summary == 'Revised 1 and dropped 0 of 1 policies after a first look at 4 runs.'
    apply(run.config.spec)
    [pol] = run.config.spec.policies
    assert pol.id == 'aid_all' and pol.revised  # same id: priors, branches and the report line up across the round


def test_stream_replans_once(llm_on, monkeypatch):
    from fastapi.testclient import TestClient
    from worldsim import api
    monkeypatch.setattr(api, 'FRAME_DELAY', 0)
    monkeypatch.setattr(api, 'REPLAN_N', 4)
    fake = llm_on({ACTORS_PHRASE: [final(ACTORS), final(REVISED)]})
    c = TestClient(api.app)
    rid = c.post('/runs', json={'prompt': 'A magnitude 8.1 quake hits Istanbul'}).json()['run_id']

    def roles():
        with c.stream('GET', f'/runs/{rid}/stream') as s:
            return [json.loads(l[6:])['agent'] for l in s.iter_lines() if l.startswith('data: {"type":"agent"')]
    first = roles()
    assert [a['status'] for a in first if a['role'] == 'replan'] == ['running', 'done']
    saved = json.loads((api.RUNS_DIR / f'{rid}.json').read_text())
    assert saved['agents']['replan']['revised'] and saved['agents']['replan']['first_plan'][0]['threshold'] == 50.0
    assert saved['config']['spec']['policies'][0]['revised']
    report = c.get(f'/runs/{rid}/report').json()
    assert report['decisions']['adaptation']['n'] == 4 and '**Who decided what**' in c.get(f'/runs/{rid}/report.md').text
    calls = fake.by_role[ACTORS_PHRASE]
    api.CACHE.clear()
    again = roles()
    assert [a['role'] for a in again if a['role'] == 'replan'] == ['replan'] and fake.by_role[ACTORS_PHRASE] == calls  # replayed, no call


def test_reporter_and_critic_stored_for_replay(llm_on, monkeypatch):
    from fastapi.testclient import TestClient
    from worldsim import api
    monkeypatch.setattr(api, 'FRAME_DELAY', 0)
    fake = llm_on({'You write two paragraphs': [final({'paragraph': 'It kills 123456 people.', 'scale_paragraph': 'The quake stays within one region.'})],
                   'You review a finished Worldsim run': [final({'flags': [{'kind': 'missing_mechanism', 'text': 'Aftershocks are not modeled.'},
                                                                           {'kind': 'inconsistent', 'text': 'It reaches 77 countries.'}]})]})
    c = TestClient(api.app)
    rid = c.post('/runs', json={'prompt': 'A magnitude 8.1 quake hits Istanbul'}).json()['run_id']
    with c.stream('GET', f'/runs/{rid}/stream') as s:
        report = next(json.loads(l[6:])['report'] for l in s.iter_lines() if l.startswith('data: {"type":"report"'))
    assert report['headline_generator'] == 'template'                       # invented number: the template headline stands
    assert report['scale']['narrative'] == 'The quake stays within one region.'
    assert [f['text'] for f in report['confidence']['flags'] if f['generator'] == 'llm'] == ['Aftershocks are not modeled.']
    saved = json.loads((api.RUNS_DIR / f'{rid}.json').read_text())['agents']
    assert saved['report_text']['scale_narrative'] and saved['voices']  # voice lines kept (empty: the fake refuses them)
    log = [json.loads(l) for l in (api.RUNS_DIR / 'calibration.jsonl').read_text().splitlines()]
    assert any(r['run_id'] == rid and r['measured']['reach']['mode'] and r['truth'] is None for r in log)
    calls = fake.calls
    api.CACHE.clear()  # fresh prepare from the run file: replay
    again = c.get(f'/runs/{rid}/report').json()
    assert again['scale']['narrative'] == report['scale']['narrative'] and fake.calls == calls  # no API call on replay
