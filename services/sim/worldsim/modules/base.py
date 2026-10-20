"""Module interface and the shared simulation context.

A module turns (context, parameters, rng) into a Trajectory. The engine runs it many times for the ensemble
(detail=False: only global metrics) and once more with detail=True for the animated median run.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from ..models import Assumption, ScenarioSpec
from ..personas import Population
from ..world import World, haversine_km

SEG_INDEX = {'children': 0, 'workers_low': 1, 'workers_mid': 2, 'workers_high': 3, 'seniors': 4}
AGE_OF_SEG = np.array([0, 1, 1, 1, 2])  # children → 0-14, workers → 15-64, seniors → 65+
STATUS = {s: i for i, s in enumerate(['unaware', 'aware', 'reacting', 'affected', 'recovered', 'adopted', 'opposed'])}
TRAITS = ['risk_tolerance', 'institutional_trust', 'media_exposure', 'price_sensitivity', 'tech_adoption', 'social_connectedness']


@dataclass
class Prior:
    """A model parameter with its range. value is the central estimate; low/high bound the ensemble draws."""
    key: str
    text: str
    value: float
    low: float
    high: float
    unit: str = ''
    origin: str = 'model'
    confidence: str = 'low'
    source: str | None = None

    def assumption(self, overridden: bool = False) -> Assumption:
        return Assumption(id=self.key, text=self.text, value=round(self.value, 6), unit=self.unit,
                          origin='user' if overridden else self.origin, confidence='high' if overridden else self.confidence,
                          source=self.source, editable=True, low=self.low, high=self.high)

    def sample(self, rng: np.random.Generator) -> float:
        lo, hi = min(self.low, self.value), max(self.high, self.value)
        if hi <= lo:
            return self.value
        return float(rng.triangular(lo, self.value, hi))


@dataclass
class Institution:
    id: str
    label: str
    lat: float
    lon: float
    iso3: str
    role: str
    voice: str
    company_id: str | None = None
    employees: float | None = None
    loc: int = 0


@dataclass
class Trajectory:
    """Outputs of one run. Arrays are indexed by step t = 0..T."""
    key: np.ndarray                      # key metric per step (global)
    metrics: list[dict[str, float]]      # global metrics per step
    outcomes: dict[str, float]           # end-of-horizon outcome metrics used in the summary table
    # detail only
    p_status: np.ndarray | None = None   # (T+1, P) int8 status codes for people personas
    p_metric: np.ndarray | None = None   # (T+1, P) persona-level metric (unit in module.persona_metric)
    i_status: np.ndarray | None = None   # (T+1, I) institution status codes
    i_metric: np.ndarray | None = None
    layers: list[dict[str, dict[str, float]]] | None = None
    events: list[dict] = field(default_factory=list)  # {t, title, cause, places, severity}
    flows: list[list[dict]] | None = None             # per step: {from:[lon,lat], to:[lon,lat], weight, kind}
    breakdown: dict[str, list[dict]] = field(default_factory=dict)  # tables for the report
    causal: dict = field(default_factory=dict)        # {nodes:[{id,label,value}], edges:[{from,to,label}]}


class Context:
    """Arrays for one scenario. Built once per run request; shared by every ensemble member."""

    def __init__(self, world: World, pop: Population, spec: ScenarioSpec, institutions: list[Institution]):
        self.world, self.pop, self.spec = world, pop, spec
        self.steps = math.ceil(spec.horizon_days / spec.step_days)
        self.dt = spec.step_days
        locs = pop.locations
        self.L = len(locs)
        self.loc_lat = np.array([l.lat for l in locs])
        self.loc_lon = np.array([l.lon for l in locs])
        self.loc_pop = np.array([l.pop for l in locs])
        self.loc_urban = np.array([l.urban for l in locs])
        self.loc_name = [l.name for l in locs]
        self.iso3 = sorted({l.iso3 for l in locs})
        self.c_idx = {c: i for i, c in enumerate(self.iso3)}
        self.C = len(self.iso3)
        self.loc_c = np.array([self.c_idx[l.iso3] for l in locs])
        self.c_pop = np.bincount(self.loc_c, weights=self.loc_pop, minlength=self.C)
        self.c_name = [world.countries[c].name if c in world.countries else c for c in self.iso3]
        self.c_lat = np.array([world.countries[c].lat for c in self.iso3])
        self.c_lon = np.array([world.countries[c].lon for c in self.iso3])
        # largest location per country (its air gateway)
        self.c_hub = np.zeros(self.C, dtype=int)
        best = np.full(self.C, -1.0)
        for i in range(self.L):
            c = self.loc_c[i]
            if self.loc_urban[i] and self.loc_pop[i] > best[c]:
                best[c], self.c_hub[c] = self.loc_pop[i], i
        for c in range(self.C):
            if best[c] < 0:
                self.c_hub[c] = int(np.flatnonzero(self.loc_c == c)[0])
        people = pop.people
        self.P = len(people)
        self.p_loc = np.array([p.loc for p in people])
        self.p_c = self.loc_c[self.p_loc]
        self.p_seg = np.array([SEG_INDEX[p.segment] for p in people])
        self.p_age = AGE_OF_SEG[self.p_seg]
        self.p_pop = np.array([p.pop for p in people])
        self.p_income = np.array([p.income if p.income else np.nan for p in people])
        self.p_traits = np.array([[p.traits[k] for k in TRAITS] for p in people])
        self.institutions = institutions
        self.I = len(institutions)
        self.i_c = np.array([self.c_idx.get(i.iso3, 0) for i in institutions], dtype=int)
        # country indicators as arrays (nan when missing)
        def ind(key):
            return np.array([world.countries[c].get(key) if c in world.countries and world.countries[c].get(key) is not None else np.nan
                             for c in self.iso3], dtype=float)
        self.ind = ind
        self.gdp_pc = ind('gdp_per_capita_usd')
        self.origin_loc = None
        if spec.origin:
            d = haversine_km(spec.origin.lat, spec.origin.lon, self.loc_lat, self.loc_lon)
            self.origin_loc = int(np.argmin(d))
            self.d_origin = d
        else:
            self.d_origin = np.full(self.L, 5000.0)
        self._cdist = None

    @property
    def c_dist(self) -> np.ndarray:
        """Country-to-country great-circle distance (km) between label points."""
        if self._cdist is None:
            self._cdist = np.stack([haversine_km(self.c_lat[i], self.c_lon[i], self.c_lat, self.c_lon) for i in range(self.C)])
        return self._cdist

    def travel_matrix(self, base_rate: float) -> np.ndarray:
        """Daily international travel probability matrix T[i, j] (gravity model on population, GDP and distance).

        Outbound share scales with income: base_rate × sqrt(GDP per capita / 10k), capped at 4× base. Destinations
        weight GDP and population over distance. A model, not observed flight data (OpenFlights ingestion is pending).
        """
        g = np.nan_to_num(self.gdp_pc, nan=np.nanmedian(self.gdp_pc) if np.isfinite(self.gdp_pc).any() else 5000.0)
        mass = np.sqrt(self.c_pop * np.maximum(g, 300)) + 1
        d = np.maximum(self.c_dist, 150)
        w = (mass[None, :]) / d ** 1.2
        np.fill_diagonal(w, 0)
        w /= w.sum(axis=1, keepdims=True) + 1e-12
        out = np.minimum(base_rate * np.sqrt(np.maximum(g, 300) / 10000), 4 * base_rate)
        return w * out[:, None]

    def loc_weight_in_country(self) -> np.ndarray:
        """Share of the country's population at each location."""
        return self.loc_pop / np.maximum(self.c_pop[self.loc_c], 1)


def awareness(ctx: Context, signal_c: np.ndarray, media: float, t_days: float) -> np.ndarray:
    """Per-persona awareness probability given a country-level news signal in [0, 1].

    awareness = 1 - exp(-k · signal · (0.3 + media_exposure)), with k a model constant. Used by all modules.
    """
    me = ctx.p_traits[:, TRAITS.index('media_exposure')]
    return 1 - np.exp(-media * signal_c[ctx.p_c] * (0.3 + me))


def monotone(new: np.ndarray, old: np.ndarray) -> np.ndarray:
    """Status codes only move forward in this release (no relapse states)."""
    return np.maximum(new, old)


class Module:
    name = 'base'
    key_metric = ''
    key_unit = ''
    persona_metric = ('', '')  # (name, unit)
    layers: list[tuple[str, str, str]] = []  # (key, label, unit)
    outcome_spec: list[tuple[str, str, str]] = []  # (key, name, unit); the first is the headline outcome
    mechanisms: list[str] = []
    confidence = 'medium'
    explain_keys: list[tuple[str, str]] = [('population', 'population'), ('gdp_per_capita_usd', 'GDP per capita $')]

    def priors(self, ctx: Context) -> list[Prior]:
        raise NotImplementedError

    def simulate(self, ctx: Context, params: dict[str, float], rng: np.random.Generator, detail: bool) -> Trajectory:
        raise NotImplementedError

    def assumptions(self, ctx: Context) -> list[Assumption]:
        return []

    def inst_text(self, role: str, v: float) -> str:
        from ..util import fmt
        return fmt(v)

    def inst_metric(self, role: str) -> tuple[str, str]:
        """(name, unit) of an institution's metric, used in bubble 'why' payloads."""
        return self.persona_metric

    def counterfactuals(self, ctx: Context) -> list[dict]:
        return []
