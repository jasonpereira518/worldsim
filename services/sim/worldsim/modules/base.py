"""Module interface and the shared simulation context.

A module turns (context, parameters, rng) into a Trajectory. The engine runs it many times for the ensemble
(detail=False: only global metrics) and once more with detail=True for the animated median run.
"""
from __future__ import annotations

import math
import re
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

    def quantile(self, q: float) -> float:
        """Inverse CDF of the same triangular distribution (used to sample a tail for escalation branches)."""
        a, c, b = min(self.low, self.value), self.value, max(self.high, self.value)
        if b <= a:
            return self.value
        q = min(max(q, 0.0), 1.0)
        if q < (c - a) / (b - a):
            return float(a + math.sqrt(q * (b - a) * (c - a)))
        return float(b - math.sqrt((1 - q) * (b - a) * (b - c)))


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
    # people materially affected by the end of the horizon, per location (each module's own definition); drives scale.reach_class
    affected_loc: np.ndarray | None = None
    # actor policies that fired: {t, day, policy, actor, action, countries, trigger} (both modes; cheap)
    decisions: list[dict] = field(default_factory=list)
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


# --- actor policies -------------------------------------------------------------------------------------------
# A module's `policy_menu` lists what actors can decide: {action: {kind, label, metric, metric_label, threshold:
# (central, low, high, unit), lag: (central, low, high) days, duration?: (central, low, high) days, scope?, source}}.
# Agents pick actions and scopes; the numbers become priors pol_<id>_threshold / _lag / _duration in the menu's ranges.

def policy_rows(pol, item: dict) -> list[tuple[str, str, float, float, float, str]]:
    """(key, text, central, low, high, unit) of one policy's priors; the agent's values use the same keys."""
    c, lo, hi, unit = item['threshold']
    rows = [(f'pol_{pol.id}_threshold', f'{pol.actor_label}: {item["label"]} when {item["metric_label"]} reaches', c, lo, hi, unit),
            (f'pol_{pol.id}_lag', f'{pol.actor_label}: days from trigger to {item["label"]}', *item['lag'], 'days')]
    if 'duration' in item:
        rows.append((f'pol_{pol.id}_duration', f'{pol.actor_label}: how long the {item["label"]} lasts', *item['duration'], 'days'))
    return rows


def policy_priors(ctx: Context, menu: dict) -> list[Prior]:
    return [Prior(k, text, c, lo, hi, unit, 'model', 'low', menu[pol.action].get('source'))
            for pol in ctx.spec.policies if pol.action in menu for k, text, c, lo, hi, unit in policy_rows(pol, menu[pol.action])]


def policy_scopes(ctx: Context) -> dict[str, np.ndarray]:
    """policy id → countries it covers (bool over ctx.iso3). The same for every ensemble member, so cached on ctx."""
    cached = getattr(ctx, '_policy_scope', None)
    if cached is None:
        cached = ctx._policy_scope = {pol.id: scope_mask(ctx, pol.scope) for pol in ctx.spec.policies}
    return cached


def scope_mask(ctx: Context, scope: str) -> np.ndarray:
    """'all' | 'origin' | 'group:<World Bank income group>' → bool over ctx.iso3."""
    mask = np.zeros(ctx.C, bool)
    if scope == 'all':
        mask[:] = True
    elif scope == 'origin' and ctx.origin_loc is not None:
        mask[ctx.loc_c[ctx.origin_loc]] = True
    elif scope.startswith('group:'):
        mask = np.array([c in ctx.world.countries and ctx.world.countries[c].income_group == scope[6:] for c in ctx.iso3])
    return mask


def fire_policies(ctx: Context, menu: dict, p: dict, t: int, obs: dict, fired: dict, ivs: list, decisions: list,
                  events: list | None = None) -> None:
    """Fire every policy whose trigger crossed at step t: append an Intervention dated t + lag (in steps) to `ivs` and a
    record to `decisions` (and a timeline event in detail mode). Country metrics fire per country, global metrics once.
    Deterministic and RNG-free, so a member's detail rerun matches it exactly."""
    from ..models import Intervention
    scopes = policy_scopes(ctx)
    for pol in ctx.spec.policies:
        item = menu.get(pol.action)
        if not item or item['metric'] not in obs:
            continue
        thr = p[f'pol_{pol.id}_threshold']
        done = fired.setdefault(pol.id, np.zeros(ctx.C, bool))
        v = obs[item['metric']]
        if np.ndim(v) == 0:
            hit = scopes[pol.id] & ~done if v >= thr else np.zeros(ctx.C, bool)
        else:
            hit = scopes[pol.id] & ~done & (v >= thr)
        if not hit.any():
            continue
        first = not done.any()  # the first firing is a key moment; later countries follow at a lower severity
        done |= hit
        lag = max(1, int(round(p[f'pol_{pol.id}_lag'] / ctx.dt)))
        countries = [ctx.iso3[c] for c in np.flatnonzero(hit)]
        dur = p.get(f'pol_{pol.id}_duration')
        ivs.append(Intervention(kind=item['kind'], day=t + lag, value=dur, countries=countries, text=f'{pol.actor_label}: {item["label"]}'))
        where = ', '.join(ctx.c_name[c] for c in np.flatnonzero(hit)[:3]) + (f' and {len(countries) - 3} more' if len(countries) > 3 else '')
        trigger = f'{item["metric_label"]} reached {thr:.3g} {item["threshold"][3]}'
        decisions.append({'t': t, 'day': (t + lag) * ctx.dt, 'policy': pol.id, 'actor': pol.actor_label, 'action': item['label'],
                          'countries': countries, 'trigger': trigger, 'rationale': pol.rationale})
        if events is not None:
            events.append({'t': t, 'title': f'{pol.actor_label}: {item["label"]}' + (f' ({where})' if item.get('level') == 'country' else ''),
                           'cause': f'{trigger}; takes effect in {lag * ctx.dt:.0f} days', 'places': [ctx.c_name[c] for c in np.flatnonzero(hit)[:5]],
                           'severity': 3 if first else 2})


# --- crowd behavior ------------------------------------------------------------------------------------------
# A module's `behavior_dims` ({dim: description}) are the population behaviors crowd agents may shift. Agents give a
# label per (cluster, dim); code maps it to a multiplier band, and each non-typical label becomes a prior
# beh_<cluster>_<dim> in that band, so the ensemble samples it, sensitivity ranks it and a detail run reproduces it.
STANCE_BANDS = {'much lower': (0.5, 0.75), 'lower': (0.75, 0.95), 'higher': (1.05, 1.35), 'much higher': (1.35, 1.8)}


def behavior_key(cluster: str, dim: str) -> str:
    return 'beh_' + re.sub(r'[^a-z0-9]+', '_', cluster.lower()).strip('_') + '_' + dim


def behavior_priors(ctx: Context, dims: dict) -> list[Prior]:
    return [Prior(behavior_key(st.cluster, dim), f'{st.label}: {dims[dim]} ({label} than typical)', round(sum(STANCE_BANDS[label]) / 2, 4),
                  *STANCE_BANDS[label], '×', 'llm', 'low', f'crowds (AI): {st.rationale}'.strip())
            for st in ctx.spec.behavior for dim, label in st.stances.items() if dim in dims and label in STANCE_BANDS]


def behavior(ctx: Context, p: dict, dim: str) -> np.ndarray:
    """Multiplier per country for one behavior dimension: 1 without a stance; the origin cluster overrides its group."""
    m = np.ones(ctx.C)
    for st in sorted(ctx.spec.behavior, key=lambda s: s.cluster == 'origin'):
        k = behavior_key(st.cluster, dim)
        if k in p:
            m[scope_mask(ctx, st.cluster)] = p[k]
    return m


def stance_of(ctx: Context, c: int) -> dict[str, str]:
    """The stance labels that apply to country index c (for voice prompts)."""
    out = {}
    for st in sorted(ctx.spec.behavior, key=lambda s: s.cluster == 'origin'):
        if scope_mask(ctx, st.cluster)[c]:
            out.update(st.stances)
    return out


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
    policy_menu: dict[str, dict] = {}  # what actor agents may decide in this module (see fire_policies)
    behavior_dims: dict[str, str] = {}  # population behaviors crowd agents may shift (see behavior)

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
