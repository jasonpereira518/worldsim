"""Contracts. Mirrors apps/web/src/lib/sim/types.ts; tests/test_contract.py keeps them aligned."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Confidence = Literal['high', 'medium', 'low']
Origin = Literal['data', 'model', 'llm', 'user', 'mock']
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
    kind: Literal['border_closure', 'lockdown', 'vaccine', 'price_change', 'tariff_change', 'aid', 'custom']
    day: int
    value: float | None = None
    countries: list[str] = Field(default_factory=list)  # empty = everywhere
    text: str


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
