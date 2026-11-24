from types import SimpleNamespace

from worldsim import llm, voices


class FakeClient:
    def __init__(self, text, stop='end_turn'):
        self.text, self.stop, self.calls = text, stop, 0
        self.messages = self
        self.beta = SimpleNamespace(messages=self)

    def create(self, **kw):
        self.calls += 1
        assert kw['output_config']['format']['type'] == 'json_schema'
        return SimpleNamespace(stop_reason=self.stop, usage=SimpleNamespace(input_tokens=1000, output_tokens=200),
                               content=[SimpleNamespace(type='text', text=self.text)])


def test_llm_bubbles_validated(monkeypatch, tmp_path):
    monkeypatch.setenv('WORLDSIM_LLM', 'on')
    monkeypatch.setattr(llm, 'CACHE_DIR', tmp_path)
    fake = FakeClient('{"items": [{"id": "a", "text": "Cases hit 12.5 per 100k here.", "decision": "stay home", "emotion": "anxious"},'
                      '{"id": "b", "text": "Half of us are sick, 50% at least.", "decision": "x", "emotion": "y"}]}')
    monkeypatch.setattr(llm, '_client', fake)
    items = [{'id': 'a', 'who': 'Workers, Hanoi', 'voice': '', 'traits': {}, 'change': 'aware → reacting', 'numbers': 'cases 3 → 12.5 per 100k'},
             {'id': 'b', 'who': 'Workers, Hue', 'voice': '', 'traits': {}, 'change': 'aware → reacting', 'numbers': 'cases 1 → 2 per 100k'}]
    b = llm.Budget()
    out = voices.llm_batch(items, b, step=1)
    assert out['a']['text'].startswith('Cases') and 'b' not in out  # invented "50%" rejected
    assert b.calls == 1 and b.usd > 0
    voices.llm_batch(items, b, step=1)
    assert fake.calls == 1 and b.cache_hits == 1  # cached


def test_concurrent_callers_never_exceed_the_call_cap():
    from concurrent.futures import ThreadPoolExecutor
    run_b = llm.Budget(max_calls=100)
    b = run_b.child(1.0, 5)
    with ThreadPoolExecutor(8) as ex:
        granted = sum(ex.map(lambda _: b.allow(), range(32)))
    assert granted == 5 and b.calls == 5 and run_b.calls == 5  # a call is counted when allowed, not when it returns


def test_budget_and_refusal(monkeypatch, tmp_path):
    monkeypatch.setenv('WORLDSIM_LLM', 'on')
    monkeypatch.setattr(llm, 'CACHE_DIR', tmp_path)
    monkeypatch.setattr(llm, '_client', FakeClient('{}', stop='refusal'))
    b = llm.Budget(max_calls=1)
    assert llm.structured('s', 'u1', {'type': 'object'}, budget=b) is None and b.refusals == 1
    assert not b.allow()
    assert llm.structured('s', 'u2', {'type': 'object'}, budget=b) is None


def test_disabled_by_default(monkeypatch):
    monkeypatch.setenv('WORLDSIM_LLM', 'off')
    assert llm.structured('s', 'u', {'type': 'object'}) is None
