"""Contracts. Mirrors apps/web/src/lib/sim/types.ts; tests/test_contract.py keeps them aligned."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

Confidence = Literal['high', 'medium', 'low']
Origin = Literal['data', 'model', 'llm', 'user', 'mock']
# Where a value comes from (docs/DATA-AUDIT.md): official (government or intergovernmental), peer-reviewed, our fit of a
# published form to official records, partly sourced (a source sets the form or range, the value is ours), or a guess.
Tier = Literal['user', 'government', 'peer_reviewed', 'fit', 'partial', 'guess']
# Audited values that are not guesses; every other model or data value is one. Update with the audit.
SOURCE_TIERS: dict[str, Tier] = {
    'latent_days': 'government', 'infectious_days': 'government', 'income_proxy': 'government',
    'bass_p': 'peer_reviewed', 'bass_q': 'peer_reviewed', 'r0': 'peer_reviewed', 'rupture_factor': 'peer_reviewed',
    'passthrough': 'peer_reviewed', 'elasticity': 'peer_reviewed', 'intensity_offset': 'peer_reviewed',
    'theta_rich': 'fit', 'beta': 'fit',
    'severity': 'partial', 'vaccine_day': 'partial', 'theta_drop': 'partial', 'export_share': 'partial',
}
PersonaStatus = Literal['unaware', 'aware', 'reacting', 'affected', 'recovered', 'adopted', 'opposed']
STATUS_CODES: list[str] = ['unaware', 'aware', 'reacting', 'affected', 'recovered', 'adopted', 'opposed']
EventType = Literal['outbreak', 'disaster', 'conflict', 'policy', 'finance', 'supply_chain', 'launch', 'corporate',
                    'election', 'climate', 'social', 'generic']
Domain = Literal['health', 'economy', 'supply_chain', 'politics', 'climate', 'tech_adoption', 'information', 'security']


class Provenance(BaseModel):
    source: str
    as_of: str | None
    confidence: Confidence
    license: str


class Assumption(BaseModel):
    id: str
    text: str
    value: float | str | None = None
    unit: str | None = None
    origin: Origin
    confidence: Confidence
    source: str | None = None
    editable: bool = False
    # prior range used by ensembles and sensitivity (numeric assumptions only)
    low: float | None = None
    high: float | None = None
    tier: Tier | None = None  # filled from the origin and SOURCE_TIERS when not given

    @model_validator(mode='after')
    def _tier(self) -> Assumption:
        if self.tier is None:  # an agent's or the mock's value is never the source's value
            self.tier = 'user' if self.origin == 'user' else 'guess' if self.origin in ('llm', 'mock') else SOURCE_TIERS.get(self.id, 'guess')
        return self


class Place(BaseModel):
    id: int
    name: str
    country: str
    iso3: str
    iso2: str
    admin1: str
    lat: float
    lon: float
    pop: float
    capital: bool
    hub: bool


class Intervention(BaseModel):
    """A user-specified policy change, e.g. borders close on day 10."""
    kind: Literal['border_closure', 'lockdown', 'vaccine', 'price_change', 'tariff_change', 'aid', 'retaliation', 'custom']
    day: int
    value: float | None = None  # rate or price change; for a policy lockdown, its duration in days (None = until the horizon)
    countries: list[str] = Field(default_factory=list)  # empty = everywhere
    text: str


ReachClass = Literal['local', 'regional', 'national', 'multi_country', 'global']


class Plausibility(BaseModel):
    """Is the premise realistic? 'impossible' stops the run with a clarifying question."""
    verdict: Literal['realistic', 'stretched', 'implausible', 'impossible']
    reasons: list[str] = Field(default_factory=list)
    adjusted_premise: str | None = None
    generator: Literal['rules', 'llm'] = 'rules'


class PriorTail(BaseModel):
    key: str
    side: Literal['upper', 'lower']


class EscalationBranch(BaseModel):
    """A path to a larger (or smaller) event, described by choices only. The engine sizes it and counts how many
    base runs reach that size; `likelihood` is the agent's label, scored against that count."""
    id: str
    title: str
    path: str
    trigger: str
    likelihood: Literal['unlikely', 'possible', 'likely'] | None = None
    tails: list[PriorTail] = Field(default_factory=list)
    disable_policies: bool = False


class AnalogBand(BaseModel):
    analog_id: str
    band: Literal['far below', 'below', 'comparable', 'above', 'far above']
    why: str = ''


class ScaleHypothesis(BaseModel):
    """The scale assessor's forecast, written before the engine's numbers exist and scored against them."""
    reach_expected: ReachClass
    reach_why: str
    analog_bands: list[AnalogBand] = Field(default_factory=list)
    branches: list[EscalationBranch] = Field(default_factory=list)
    generator: Literal['rules', 'llm'] = 'llm'


class AgentStep(BaseModel):
    """One agent role's work on a run: streamed as an `agent` event and kept in the run file for replays."""
    role: str
    model: str
    status: Literal['running', 'done', 'skipped', 'failed']
    summary: str
    usd: float = 0.0
    evidence: list[str] = Field(default_factory=list)


class Policy(BaseModel):
    """An actor's conditional decision, chosen from the module's policy menu: when `trigger_metric` crosses a threshold
    in the scoped countries, take `action` after a lag. Threshold, lag and duration are priors (pol_<id>_*), so the
    ensemble samples them and sensitivity ranks them; the policy itself carries no free numbers."""
    id: str
    actor_id: str
    actor_label: str
    action: str
    scope: str  # 'origin' | 'all' | 'group:<World Bank income group>'
    trigger_metric: str
    rationale: str = ''
    evidence: list[str] = Field(default_factory=list)
    revised: bool = False


StanceLabel = Literal['much lower', 'lower', 'typical', 'higher', 'much higher']


class CrowdStance(BaseModel):
    """How one population cluster behaves relative to the module's typical assumption, per behavior dimension. Labels
    only: code maps each label to a multiplier band, which becomes a prior beh_<cluster>_<dim>."""
    cluster: str  # 'origin' | 'group:<World Bank income group>'
    label: str
    stances: dict[str, StanceLabel]
    rationale: str = ''
    evidence: list[str] = Field(default_factory=list)


class ScenarioSpec(BaseModel):
    title: str
    prompt: str
    event_type: EventType
    domains: list[Domain]
    origin: Place | None
    global_: bool = Field(alias='global')
    start_date: str
    horizon_days: int
    step_days: int
    actors: list[str]
    mechanisms: list[str]
    assumptions: list[Assumption]
    interventions: list[Intervention] = Field(default_factory=list)
    clarifying_question: str | None = None
    engine: Literal['mock-m0', 'worldsim']
    module: str
    parser: Literal['rules', 'llm']
    confidence: Confidence
    plausibility: Plausibility | None = None
    scale: ScaleHypothesis | None = None
    policies: list[Policy] = Field(default_factory=list)
    behavior: list[CrowdStance] = Field(default_factory=list)

    model_config = {'populate_by_name': True}


class Persona(BaseModel):
    id: str
    kind: Literal['people', 'institution']
    label: str
    location: dict
    population_represented: float
    demographics: dict
    traits: dict
    context: dict
    voice: str
    segment: str


class Delta(BaseModel):
    id: str
    status: PersonaStatus
    metric: float | None = None


class Why(BaseModel):
    event: str
    metric: str
    before: float
    after: float
    unit: str
    source: str | None = None


class Bubble(BaseModel):
    id: str
    persona_id: str
    t: int
    text: str = Field(max_length=140)
    sentiment: Literal[-1, 0, 1]
    priority: float
    why: Why
    decision: str | None = None
    emotion: str | None = None
    generator: Literal['template', 'llm'] = 'template'


class SimEvent(BaseModel):
    id: str
    t: int
    date: str
    title: str
    cause: str
    places: list[str]
    severity: Literal[1, 2, 3]


class Flow(BaseModel):
    from_: tuple[float, float] = Field(alias='from')
    to: tuple[float, float]
    weight: float
    kind: Literal['spread', 'trade', 'movement', 'adoption']

    model_config = {'populate_by_name': True}


class Frame(BaseModel):
    t: int
    date: str
    deltas: list[Delta]
    bubbles: list[Bubble]
    events: list[SimEvent]
    flows: list[Flow]
    metrics: dict[str, float]
    # per-country values of the choropleth layers, e.g. {'cases_per_100k': {'VNM': 12.3}}
    layers: dict[str, dict[str, float]] = Field(default_factory=dict)
    # ensemble band of the key metric at this step: [p5, p25, p50, p75, p95]
    band: list[float] | None = None


class SummaryMetric(BaseModel):
    name: str
    value: float
    unit: str
    low: float | None = None   # 5th percentile
    high: float | None = None  # 95th percentile
    low50: float | None = None  # 25th
    high50: float | None = None  # 75th
    confidence: Confidence
    source: str | None = None


class Summary(BaseModel):
    headline: str
    metrics: list[SummaryMetric]
    note: str


class RunConfig(BaseModel):
    run_id: str
    seed: int
    spec: ScenarioSpec
    created_at: str
    data_snapshot: str
    engine_version: str
    ensemble_size: int
    parent_run_id: str | None = None
    branch_at: int | None = None
    label: str | None = None
