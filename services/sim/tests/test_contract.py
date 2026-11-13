"""The web client and this service share one contract: apps/web/src/lib/sim/types.ts ↔ worldsim/models.py.
Every field the service sends must be declared in TypeScript; every required TypeScript field must be sent."""
import re
from pathlib import Path

import pytest

from worldsim import models

TS = (Path(__file__).resolve().parents[3] / 'apps' / 'web' / 'src' / 'lib' / 'sim' / 'types.ts').read_text()
PAIRS = ['Assumption', 'Intervention', 'ScenarioSpec', 'Persona', 'Delta', 'Bubble', 'SimEvent', 'Frame', 'SummaryMetric', 'Summary', 'RunConfig',
         'Plausibility', 'PriorTail', 'EscalationBranch', 'AnalogBand', 'ScaleHypothesis', 'AgentStep', 'Policy', 'CrowdStance']


def ts_fields(name: str) -> dict[str, bool]:
    """field → required, for `export interface Name { ... }` (top-level keys only)."""
    m = re.search(rf'export interface {name}\b[^{{]*\{{', TS)
    assert m, f'interface {name} not found in types.ts'
    i, depth, body = m.end(), 1, []
    while depth:
        ch = TS[i]
        depth += ch == '{'
        depth -= ch == '}'
        body.append(ch if depth == 1 or (depth == 2 and ch == '{') else ('' if depth > 1 else ch))
        i += 1
    text = ''.join(body)
    text = re.sub(r'/\*.*?\*/|//[^\n]*', '', text, flags=re.S)
    return {k: q != '?' for k, q in re.findall(r'^\s*([a-z_0-9]+)(\??)\s*:', text, flags=re.M)}


@pytest.mark.parametrize('name', PAIRS)
def test_python_and_typescript_agree(name):
    model = getattr(models, name)
    py = {(f.alias or k): f.is_required() for k, f in model.model_fields.items()}
    ts = ts_fields(name)
    missing_in_ts = set(py) - set(ts)
    assert not missing_in_ts, f'{name}: service sends fields the web client does not declare: {sorted(missing_in_ts)}'
    required_not_sent = {k for k, req in ts.items() if req and k not in py}
    assert not required_not_sent, f'{name}: web client requires fields the service never sends: {sorted(required_not_sent)}'
