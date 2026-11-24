"""Prompt → ScenarioSpec. Rules always run; the intake agent (when enabled) refines classification, place and actors
and judges plausibility. Numbers in the spec come only from the prompt text or from module defaults."""
from __future__ import annotations

import datetime as dt
import re

from . import T0, llm
from .agents import intake
from .models import Assumption, Intervention, Place, Plausibility, ScenarioSpec
from .world import World, gazetteer

RULES: list[tuple[str, str, list[str], int, int, list[str], list[str]]] = [
    ('outbreak', r'\b(outbreak|pandemic|epidemic|virus|variant|h5n1|h1n1|ebola|influenza|flu|transmission|infect\w*|cholera|measles|covid|sars|mers|pathogen)\b',
     ['health', 'economy', 'information'], 365, 1, ['human-to-human transmission', 'air-travel seeding', 'health-system capacity', 'behavioral response'],
     ['WHO', 'health ministries', 'hospitals', 'airlines']),
    ('disaster', r'\b(earthquake|quake|magnitude|tsunami|hurricane|cyclone|typhoon|flood\w*|wildfire|eruption|volcano|landslide)\b',
     ['security', 'economy', 'supply_chain'], 90, 1, ['ground shaking and damage', 'casualties and displacement', 'infrastructure outage', 'relief and recovery'],
     ['civil protection agency', 'hospitals', 'insurers', 'utilities']),
    ('policy', r'\b(tariffs?|sanctions?|bans?|imposes?|regulat\w*|legislat\w*|embargo|quota|subsid\w*|duty|duties)\b',
     ['economy', 'supply_chain', 'politics'], 364, 7, ['price pass-through', 'trade diversion', 'retaliation', 'substitution'],
     ['regulators', 'importers', 'manufacturers', 'consumers']),
    ('conflict', r'\b(war|invades?|invasion|conflict|missiles?|troops|ceasefire|coup|insurgen\w*|airstrikes?|blockades?)\b',
     ['security', 'politics', 'economy'], 180, 1, ['escalation', 'displacement', 'sanctions', 'commodity shock'],
     ['governments', 'UNHCR', 'energy markets', 'neighboring states']),
    ('finance', r'\b(defaults?|bank run|crash\w*|bankrupt\w*|rate (hike|cut)|devalu\w*|credit crunch|recession|stock market|sovereign debt)\b',
     ['economy', 'information'], 180, 1, ['market reaction', 'contagion', 'credit tightening', 'policy response'],
     ['central banks', 'banks', 'investors', 'rating agencies']),
    ('supply_chain', r'\b(canal|strait|shipping|port closure|chip shortage|semiconductor|supply chain|chokepoint)\b',
     ['supply_chain', 'economy'], 120, 1, ['network disruption', 'inventory buffers', 'rerouting', 'bottlenecks'],
     ['shippers', 'manufacturers', 'ports', 'insurers']),
    ('launch', r'\b(launch\w*|releases?|unveils?|headset|iphone|smartphone|rollout|ships|product|device)\b',
     ['tech_adoption', 'economy', 'supply_chain'], 364, 7, ['media awareness', 'Bass diffusion by segment', 'price affordability', 'supply constraints', 'competitor response'],
     ['retailers', 'suppliers', 'competitors']),
    ('corporate', r'\b(acqui\w*|merger|m&a|recalls?|layoffs?|ipo|spin-?off)\b',
     ['economy', 'information'], 120, 1, ['market reaction', 'workforce effects', 'customer response'], ['regulators', 'investors']),
    ('election', r'\b(elections?|referendum|ballot|wins the presidency)\b',
     ['politics', 'economy', 'information'], 90, 1, ['opinion dynamics', 'policy expectations', 'market repricing'], ['parties', 'voters', 'media']),
    ('climate', r'\b(heat ?wave|drought|monsoon|el ni[ñn]o|sea level|glacier|emissions)\b',
     ['climate', 'economy', 'health'], 180, 7, ['exposure', 'agricultural yield', 'energy demand', 'adaptation'], ['farmers', 'utilities', 'governments']),
    ('social', r'\b(protests?|boycott|viral|trend\w*|strikes?|movement|festival|world cup|olympics)\b',
     ['information', 'politics', 'economy'], 60, 1, ['social amplification', 'attention cycle', 'institutional response'], ['media', 'platforms', 'authorities']),
]
GENERIC = ('generic', '', ['economy', 'information'], 120, 1, ['closest-analog stock-and-flow (generic fallback)'], ['governments', 'media', 'markets'])
MODULE_FOR = {'outbreak': 'epidemiology', 'disaster': 'disaster', 'launch': 'launch', 'policy': 'trade', 'supply_chain': 'trade'}

DEMONYMS = {
    'chinese': 'CHN', 'vietnamese': 'VNM', 'american': 'USA', 'japanese': 'JPN', 'korean': 'KOR', 'south korean': 'KOR', 'indian': 'IND',
    'russian': 'RUS', 'german': 'DEU', 'french': 'FRA', 'british': 'GBR', 'brazilian': 'BRA', 'mexican': 'MEX', 'turkish': 'TUR',
    'iranian': 'IRN', 'israeli': 'ISR', 'saudi': 'SAU', 'taiwanese': 'TWN', 'indonesian': 'IDN', 'nigerian': 'NGA', 'egyptian': 'EGY',
    'canadian': 'CAN', 'australian': 'AUS', 'italian': 'ITA', 'spanish': 'ESP', 'ukrainian': 'UKR', 'pakistani': 'PAK', 'filipino': 'PHL',
    'thai': 'THA', 'european union': 'BEL', 'the eu': 'BEL', 'eu': 'BEL', 'uk': 'GBR', 'us': 'USA', 'usa': 'USA', 'united states': 'USA',
}
# Company aliases → snapshot id prefix (resolved against the company store; HQ comes from the store, never from here).
COMPANY_ALIASES = {'apple': 'apple', 'meta': 'meta', 'facebook': 'meta', 'samsung': 'samsung', 'sony': 'sony', 'tsmc': 'tsmc',
                   'foxconn': 'foxconn', 'hon hai': 'foxconn', 'byd': 'byd', 'volkswagen': 'volkswagen', 'vw': 'volkswagen',
                   'maersk': 'maersk', 'lufthansa': 'lufthansa', 'best buy': 'best-buy', 'tesla': 'tesla', 'nvidia': 'nvidia',
                   'google': 'alphabet', 'alphabet': 'alphabet', 'microsoft': 'microsoft', 'amazon': 'amazon', 'toyota': 'toyota'}

MONTHS = ['jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec']


def _has(text: str, word: str) -> bool:
    return re.search(rf'(^|[^a-z]){re.escape(word)}([^a-z]|$)', text) is not None


def find_place(text: str, w: World) -> Place | None:
    lower = text.lower()
    best, best_len = None, 0
    cities = w.city_by_name()
    capital = {}
    for c in w.cities:
        cur = capital.get(c.iso3)
        if cur is None or (c.capital and not cur.capital) or (c.capital == cur.capital and c.pop > cur.pop):
            capital[c.iso3] = c

    def consider(key, city):
        nonlocal best, best_len
        if city and len(key) > best_len and _has(lower, key):
            best, best_len = city, len(key)

    for k, c in cities.items():
        if len(k) > 3:
            consider(k, c)
    seed = best
    for iso3, country in w.countries.items():
        consider(country.name.lower(), capital.get(iso3))
    for k, iso3 in DEMONYMS.items():
        consider(k, capital.get(iso3))
    # lookup-only places, matched as written (capitalized) so "reading" or "nice" in a sentence is not a place; a city
    # named in a country beats the country itself ("Izmit, Turkey" is Izmit, not Ankara)
    from_country = best is not None and best is not seed
    for names, c in gazetteer():
        for n in names:
            if len(n) > 3 and (len(n) > best_len or (from_country and c.iso3 == best.iso3)) \
                    and re.search(rf'(^|[^A-Za-z]){re.escape(n)}([^A-Za-z]|$)', text):
                best, best_len, from_country = c, len(n), False
    if best is None:
        return None
    return Place(id=best.id, name=best.name, country=best.country, iso3=best.iso3, iso2='', admin1=best.admin1,
                 lat=best.lat, lon=best.lon, pop=best.pop, capital=best.capital, hub=best.hub)


def find_companies(text: str, w: World) -> list[str]:
    lower = text.lower()
    found = []
    for alias, cid in COMPANY_ALIASES.items():
        if _has(lower, alias):
            match = next((k for k in w.companies if k == cid or k.startswith(cid + '-')), None)
            found.append(match or cid)
    for cid, c in w.companies.items():
        if len(c.name) > 4 and _has(lower, c.name.lower()) and cid not in found:
            found.append(cid)
    return list(dict.fromkeys(found))


def parse_start_date(text: str, t0: str = T0) -> str:
    base = dt.date.fromisoformat(t0)
    lower = text.lower()
    m = re.search(r'\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+(\d{1,2})(?:st|nd|rd|th)?(?:,?\s+(\d{4}))?', lower)
    if m:
        d = dt.date(int(m[3]) if m[3] else base.year, MONTHS.index(m[1]) + 1, int(m[2]))
        if not m[3] and d < base:
            d = d.replace(year=d.year + 1)
        return d.isoformat()
    m = re.search(r'\bin (\d+) (day|week|month)s?\b', lower) or re.search(r'\bnext (week|month|year)\b', lower)
    if m:
        n, u = (int(m[1]), m[2]) if m.lastindex == 2 else (1, m[1])
        if u == 'day':
            base += dt.timedelta(days=n)
        elif u == 'week':
            base += dt.timedelta(days=7 * n)
        elif u == 'month':
            month = base.month - 1 + n
            base = base.replace(year=base.year + month // 12, month=month % 12 + 1)
        else:
            base = base.replace(year=base.year + 1)
        return base.isoformat()
    if 'tomorrow' in lower:
        return (base + dt.timedelta(days=1)).isoformat()
    return t0


INTERVENTION_RULES = [
    (r'borders?\s+(?:close|closed|closing|shut)', 'border_closure'),
    (r'(?:lockdown|stay[- ]at[- ]home|schools?\s+close)', 'lockdown'),
    (r'vaccines?\s+(?:arrive|available|rollout|roll out|ready)', 'vaccine'),
    (r'(?:aid|relief)\s+(?:arrives|surge|doubles?)', 'aid'),
]


def parse_interventions(text: str) -> list[Intervention]:
    lower = text.lower()
    out = []
    for pat, kind in INTERVENTION_RULES:
        m = re.search(pat + r'.*?\bday\s+(\d+)', lower) or re.search(r'\bday\s+(\d+)\b.*?' + pat, lower)
        if m:
            out.append(Intervention(kind=kind, day=int(m.group(1)), text=text.strip()))
    m = re.search(r'(\d+(?:\.\d+)?)\s?%\s+(lower|higher|cheaper|more expensive)\s+price', lower) or \
        re.search(r'price\s+(?:cut|drop|lowered|reduced)\s+(?:by\s+)?(\d+(?:\.\d+)?)\s?%', lower)
    if m:
        pct = float(m.group(1))
        sign = 1 if (m.lastindex == 2 and m.group(2) in ('higher', 'more expensive')) else -1
        out.append(Intervention(kind='price_change', day=0, value=sign * pct, text=text.strip()))
    m = re.search(r'tariffs?\s+(?:to|at|of)\s+(\d+(?:\.\d+)?)\s?%', lower)
    if m and re.search(r'\b(what if|instead|rerun|re-run)\b', lower):
        out.append(Intervention(kind='tariff_change', day=0, value=float(m.group(1)), text=text.strip()))
    return out


def rules_plausibility(assumptions: list[Assumption], text: str = '') -> Plausibility | None:
    """Hard physical limits checked without an LLM. None means no rule applies (the premise is not judged)."""
    mag = next((a.value for a in assumptions if a.id == 'magnitude'), None)
    if isinstance(mag, (int, float)):
        if mag > 9.6:
            fixed = re.sub(r'(magnitude\s?)\d{1,2}(?:\.\d)?', r'\g<1>9.0', text, flags=re.I) if text else None
            return Plausibility(verdict='impossible', reasons=['No earthquake above magnitude 9.5 has been recorded (Valdivia 1960, USGS); '
                                                               'fault lengths on Earth cap moment magnitude near that size.'],
                                adjusted_premise=fixed if fixed and fixed != text else None)
        if mag >= 9.0:
            return Plausibility(verdict='stretched', reasons=['Only a handful of magnitude 9 or larger earthquakes have been recorded since 1900 (USGS), all on subduction zones.'])
    return None


def parse_prompt(prompt: str, w: World, answers: dict | None = None, budget: llm.Budget | None = None, audit: list | None = None) -> ScenarioSpec:
    text = prompt.strip()
    lower = text.lower()
    rule = next((r for r in RULES if re.search(r[1], lower)), GENERIC)
    etype = rule[0]
    parser = 'rules'
    place = find_place((answers or {}).get('origin') or '', w) or find_place(text, w)
    actors_extra: list[str] = []
    mechanisms = list(rule[5])
    clarify = None
    title = text[0].upper() + text[1:] if text else text
    plausibility = None

    out = intake(text, w, budget, audit)
    if out:
        parser = 'llm'
        etype = out['event_type']
        rule = next((r for r in RULES if r[0] == etype), GENERIC)
        if out.get('origin_place') and not place:
            place = find_place(out['origin_place'], w)
        actors_extra = out.get('actors') or []
        mechanisms = out.get('mechanisms') or mechanisms
        if out.get('needs_clarification') and not place:
            clarify = out.get('clarifying_question')
        title = out.get('title') or title
        plausibility = out['plausibility']

    companies = find_companies(text, w)
    hq = None
    if companies and companies[0] in w.companies:
        c = w.companies[companies[0]]
        if c.lat is not None:
            hq = Place(id=-1, name=c.city or c.name, country=w.countries[c.country_iso3].name if c.country_iso3 in w.countries else '',
                       iso3=c.country_iso3 or '', iso2='', admin1='', lat=c.lat, lon=c.lon, pop=0, capital=False, hub=False)
    is_global = etype in ('launch', 'finance', 'climate') or bool(re.search(r'\b(global(ly)?|worldwide|world)\b', lower))
    origin = place or hq
    if not origin and not is_global and clarify is None:
        clarify = 'Where does this start? Name a city or country.'

    assumptions = [
        Assumption(id='t0', text=f'Simulated today is {T0}', origin='user', confidence='high'),
        Assumption(id='horizon_days', text=f'Horizon {rule[3]} days in steps of {rule[4]} day(s)', value=rule[3], unit='days',
                   origin='model', confidence='medium', editable=True, low=7, high=730),
    ]
    price = re.search(r'\$\s?(\d[\d,]*(?:\.\d+)?)', text)
    if price:
        assumptions.append(Assumption(id='price_usd', text=f'Price ${price[1]}', value=float(price[1].replace(',', '')), unit='USD',
                                      origin='user', confidence='high', editable=True))
    pct = re.search(r'(\d+(?:\.\d+)?)\s?%', text)
    if pct and etype in ('policy', 'supply_chain'):
        assumptions.append(Assumption(id='tariff_pct', text=f'Tariff rate {pct[1]}%', value=float(pct[1]), unit='%',
                                      origin='user', confidence='high', editable=True))
    mag = re.search(r'magnitude\s?(\d{1,2}(?:\.\d)?)|\bm\s?(\d\.\d)\b', lower)
    if mag:
        assumptions.append(Assumption(id='magnitude', text=f'Magnitude {mag[1] or mag[2]}', value=float(mag[1] or mag[2]),
                                      origin='user', confidence='high', editable=True))
    if hq and not place:
        assumptions.append(Assumption(id='origin_hq', text=f'Origin set to the {w.companies[companies[0]].name} headquarters (company store)',
                                      origin='data', confidence='medium'))
    company_names = [w.companies[c].name if c in w.companies else c for c in companies]
    for c in companies:
        if c not in w.companies:
            assumptions.append(Assumption(id=f'company_{c}', text=f'"{c}" is not in the company store; treated as a generic actor (live resolver arrives with the entity-resolution job)',
                                          origin='data', confidence='low'))
    module = MODULE_FOR.get(etype, 'generic')
    if module == 'launch':
        assumptions.append(Assumption(id='launch_date', text=f'Launch date {parse_start_date(text)}', value=parse_start_date(text),
                                      origin='user' if parse_start_date(text) != T0 else 'model', confidence='high' if parse_start_date(text) != T0 else 'medium'))
    if etype == 'disaster' and not re.search(r'quake|magnitude|tsunami', lower):
        module = 'generic'  # hydro-meteorological hazards use the generic module until their hazard models land
    hard = rules_plausibility(assumptions, text)
    if hard and (hard.verdict == 'impossible' or plausibility is None):
        plausibility = hard  # physical limits outrank the intake agent's judgment
    if plausibility and plausibility.verdict == 'impossible':
        clarify = f'This premise looks impossible: {plausibility.reasons[0] if plausibility.reasons else "it breaks a physical limit"}' + \
                  (f' Try: "{plausibility.adjusted_premise}"' if plausibility.adjusted_premise else ' Please rephrase it.')
    return ScenarioSpec(
        title=title[:90], prompt=text, event_type=etype, domains=rule[2], origin=origin, **{'global': is_global},
        start_date=parse_start_date(text), horizon_days=rule[3], step_days=rule[4],
        actors=list(dict.fromkeys(company_names + actors_extra + ([origin.country] if origin and origin.country else []) + rule[6])),
        mechanisms=mechanisms, assumptions=assumptions, interventions=parse_interventions(text), clarifying_question=clarify,
        engine='worldsim', module=module, parser=parser, confidence='low' if module == 'generic' else 'medium', plausibility=plausibility,
    )
