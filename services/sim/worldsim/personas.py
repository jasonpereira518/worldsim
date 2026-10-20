"""Persona generator: population-weighted segments built from country distributions.

Locations: every Natural Earth city (scaled so cities never exceed the country's urban population) plus one
"rest of country" location holding the remainder, so segment populations sum to the World Bank national total.
Segments per location: children 0-14, adults 65+, and working-age adults split into income quantiles
(bottom 50%, middle 40%, top 10%) of a lognormal fitted to GDP per capita and the Gini index.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from statistics import NormalDist

from .models import Assumption
from .util import clamp01, unit
from .world import World

N = NormalDist()
GINI_PRIOR = 38.0  # used only when a country has no Gini observation; flagged as an assumption
INCOME_REF = 20000.0  # USD; price-sensitivity half point. Model constant, labeled.


def sigma_from_gini(gini: float) -> float:
    """Lognormal shape from Gini: G = 2Φ(σ/√2) − 1."""
    g = min(max(gini / 100, 0.05), 0.8)
    return math.sqrt(2) * N.inv_cdf((g + 1) / 2)


def quantile_mean(mean: float, sigma: float, p1: float, p2: float) -> float:
    """Mean income of the [p1, p2] quantile slice of a lognormal with the given mean."""
    lo = 0.0 if p1 <= 0 else N.cdf(N.inv_cdf(p1) - sigma)
    hi = 1.0 if p2 >= 1 else N.cdf(N.inv_cdf(p2) - sigma)
    return mean * (hi - lo) / (p2 - p1)


def share_above(mean: float, sigma: float, threshold: float, p1: float = 0.0, p2: float = 1.0) -> float:
    """Fraction of the [p1, p2] quantile slice whose income exceeds `threshold`."""
    if threshold <= 0:
        return 1.0
    mu = math.log(mean) - sigma ** 2 / 2
    p_th = N.cdf((math.log(threshold) - mu) / sigma)  # population quantile of the threshold
    return clamp01((p2 - max(p1, min(p_th, p2))) / (p2 - p1))


@dataclass
class Segment:
    key: str
    label: str
    age_band: str
    p1: float = 0.0
    p2: float = 1.0
    income_band: str = 'mixed'
    voice: str = ''


SEGMENTS = [
    Segment('children', 'Households with children', '0-14', voice='a parent: school, childcare, costs'),
    Segment('workers_low', 'Lower-income workers', '15-64', 0.0, 0.5, 'bottom 50%', 'blunt, daily wages and prices'),
    Segment('workers_mid', 'Middle-income workers', '15-64', 0.5, 0.9, 'middle 40%', 'practical, commute and bills'),
    Segment('workers_high', 'Higher-income professionals', '15-64', 0.9, 1.0, 'top 10%', 'confident, early adopter, travels'),
    Segment('seniors', 'Adults 65+', '65+', voice='cautious, family and health first'),
]


@dataclass
class PersonaRec:
    """Internal persona with numbers the modules need (the API model is built from it)."""
    id: str
    kind: str
    label: str
    lat: float
    lon: float
    iso3: str
    city: str
    admin1: str
    loc: int  # location index
    segment: str
    pop: float
    income: float | None  # mean annual income proxy, USD
    income_p: tuple[float, float]
    sigma: float | None
    traits: dict[str, float]
    demographics: dict[str, str]
    voice: str
    urban: bool
    context: dict = field(default_factory=dict)


@dataclass
class Location:
    idx: int
    name: str
    iso3: str
    lat: float
    lon: float
    pop: float
    urban: bool
    hub: bool
    admin1: str = ''


@dataclass
class Population:
    locations: list[Location]
    people: list[PersonaRec]
    assumptions: list[Assumption]


def build_population(w: World) -> Population:
    locs: list[Location] = []
    people: list[PersonaRec] = []
    missing_gini, missing_pop, missing_gdp = [], [], []
    by_country: dict[str, list] = {}
    for c in w.cities:
        by_country.setdefault(c.iso3, []).append(c)

    for iso3, country in sorted(w.countries.items()):
        cities = by_country.get(iso3, [])
        pop = country.population
        if pop is None:
            if not cities:
                continue
            missing_pop.append(iso3)
        urban_pct = country.get('urban_pct')
        urban_pop = pop * urban_pct / 100 if pop and urban_pct is not None else None
        city_total = sum(c.pop for c in cities)
        scale = 1.0
        if urban_pop is not None and city_total > urban_pop > 0:
            scale = urban_pop / city_total
        if pop is not None and city_total * scale > pop:
            scale = pop / city_total
        here: list[Location] = []
        for c in cities:
            here.append(Location(len(locs) + len(here), c.name, iso3, c.lat, c.lon, c.pop * scale, True, c.hub, c.admin1))
        if pop is not None:
            rest = pop - sum(l.pop for l in here)
            if rest > 1000:
                here.append(Location(len(locs) + len(here), f'Rest of {country.name}', iso3, country.lat, country.lon, rest, False, False))
        locs.extend(here)

        a0 = country.get('age_0_14_pct')
        a65 = country.get('age_65_plus_pct')
        shares = {'children': (a0 if a0 is not None else 25.0) / 100, 'seniors': (a65 if a65 is not None else 9.0) / 100}
        work = max(0.0, 1 - shares['children'] - shares['seniors'])
        gdp = country.get('gdp_per_capita_usd')
        gini = country.get('gini')
        if gini is None:
            missing_gini.append(iso3)
        if gdp is None:
            missing_gdp.append(iso3)
        sigma = sigma_from_gini(gini if gini is not None else GINI_PRIOR)
        internet = (country.get('internet_users_pct') or 0) / 100 if country.get('internet_users_pct') is not None else None
        mobile = country.get('mobile_subs_per100')

        for loc in here:
            for s in SEGMENTS:
                if s.key in shares:
                    share = shares[s.key]
                else:
                    share = work * (s.p2 - s.p1)
                spop = loc.pop * share
                if spop < 1:
                    continue
                pid = f'p_{iso3}_{loc.idx}_{s.key}'.lower()
                income = None
                if gdp is not None:
                    income = quantile_mean(gdp, sigma, s.p1, s.p2) if s.key.startswith('workers') else gdp
                age_f = {'seniors': 0.6, 'children': 0.9}.get(s.key, 1.0)
                inc_f = {'workers_low': 0.8, 'workers_high': 1.15}.get(s.key, 1.0)
                net = internet if internet is not None else 0.5
                traits = {
                    'risk_tolerance': clamp01({'seniors': 0.3, 'children': 0.4}.get(s.key, 0.55) + 0.2 * (unit(pid, 'r') - 0.5)),
                    'institutional_trust': clamp01(0.5 + 0.3 * (unit(pid, 'trust') - 0.5)),
                    'media_exposure': clamp01(0.5 * net + 0.5 * min((mobile or 80) / 120, 1.0) + 0.1 * (unit(pid, 'm') - 0.5)),
                    'price_sensitivity': clamp01(1 - (income or 8000) / ((income or 8000) + INCOME_REF)),
                    'tech_adoption': clamp01(net * age_f * inc_f + 0.1 * (unit(pid, 't') - 0.5)),
                    'social_connectedness': clamp01((0.65 if loc.urban else 0.5) + 0.2 * (unit(pid, 's') - 0.5)),
                }
                traits = {k: round(v, 2) for k, v in traits.items()}
                place = loc.name if loc.urban else loc.name.replace('Rest of ', 'towns and rural ')
                people.append(PersonaRec(
                    id=pid, kind='people', label=f'{s.label}, {place}', lat=loc.lat, lon=loc.lon, iso3=iso3,
                    city=loc.name, admin1=loc.admin1, loc=loc.idx, segment=s.key, pop=spop, income=income,
                    income_p=(s.p1, s.p2), sigma=sigma, traits=traits, urban=loc.urban, voice=s.voice,
                    demographics={'age_band': s.age_band, 'income_band': s.income_band,
                                  'income_usd': f'{income:,.0f}' if income else 'unknown',
                                  'urban_rural': 'urban' if loc.urban else 'towns/rural',
                                  'country_income_group': country.income_group or 'unknown'},
                    context={'country_profile_ref': iso3,
                             'local_conditions': [f'{country.name}: internet {net * 100:.0f}%' if internet is not None else f'{country.name}: internet use unknown']},
                ))

    assumptions = [
        Assumption(id='income_proxy', text='Household income proxied by GDP per capita (World Bank), split by a lognormal fitted to the Gini index',
                   origin='model', confidence='medium'),
        Assumption(id='trust_prior', text='Institutional trust is a neutral prior (0.35-0.65); survey data (WVS, Gallup) arrives in a later data release',
                   origin='model', confidence='low'),
        Assumption(id='rest_of_country', text='Population outside listed cities is placed at each country label point',
                   origin='model', confidence='medium'),
    ]
    if missing_gini:
        assumptions.append(Assumption(id='gini_prior', text=f'No Gini observation for {len(missing_gini)} countries; Gini {GINI_PRIOR:.0f} prior used',
                                      value=GINI_PRIOR, origin='model', confidence='low'))
    if missing_pop:
        assumptions.append(Assumption(id='pop_missing', text=f'{len(missing_pop)} territories lack World Bank population; Natural Earth metro estimates used',
                                      origin='data', confidence='low'))
    if missing_gdp:
        assumptions.append(Assumption(id='gdp_missing', text=f'{len(missing_gdp)} countries lack GDP per capita; their incomes are unknown and excluded from affordability',
                                      origin='data', confidence='low'))
    if not w.available:
        assumptions.append(Assumption(id='no_snapshot', text='No data snapshot found: run the Milestone 1 pipeline. Cities only, no indicators',
                                      origin='data', confidence='low'))
    return Population(locs, people, assumptions)
