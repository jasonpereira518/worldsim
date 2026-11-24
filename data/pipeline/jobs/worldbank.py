"""World Bank: WDI indicators (incl. UN WPP age structure in 5-year bands, as republished in WDI) and the country classification."""
from __future__ import annotations

from . import prov

API = 'https://api.worldbank.org/v2'
YEARS = '2000:2025'
NON_ISO = {'CHI'}  # Channel Islands: a World Bank economy without an ISO 3166-1 code
SPARSE = {'SI.POV.GINI', 'SH.MED.BEDS.ZS', 'SH.MED.PHYS.ZS'}  # irregular surveys, often years old → medium confidence
# Plausible bounds per key. A value outside them is kept exactly as published but marked low confidence
# (e.g. CAF life expectancy 18.8 in 2022, FJI 574 mobile subscriptions per 100 in 2024). Age keys: 0-100.
PLAUSIBLE = {
    'population': (5e2, 2e9), 'population_female': (2e2, 1e9), 'population_male': (2e2, 1e9), 'urban_pct': (0, 100),
    'life_expectancy': (25, 95), 'gdp_usd': (1e7, 5e13), 'merch_exports_usd': (0, 1e13), 'gdp_ppp': (1e7, 5e13), 'gdp_per_capita_usd': (50, 3e5),
    'gdp_growth_pct': (-70, 160), 'inflation_pct': (-40, 1e5), 'unemployment_pct': (0, 60), 'internet_users_pct': (0, 100),
    'mobile_subs_per100': (0, 450), 'hospital_beds_per1000': (0, 30), 'physicians_per1000': (0, 15), 'gini': (15, 75),
}


def plausible(key: str, value: float) -> bool:
    lo, hi = PLAUSIBLE.get(key, (0, 100) if key.startswith('age_') else (float('-inf'), float('inf')))
    return lo <= value <= hi

CORE = [
    ('SP.POP.TOTL', 'population', 'Population, total', 'people'),
    ('SP.POP.TOTL.FE.IN', 'population_female', 'Population, female', 'people'),
    ('SP.POP.TOTL.MA.IN', 'population_male', 'Population, male', 'people'),
    ('SP.URB.TOTL.IN.ZS', 'urban_pct', 'Urban population', '% of total population'),
    ('SP.DYN.LE00.IN', 'life_expectancy', 'Life expectancy at birth', 'years'),
    ('SP.POP.0014.TO.ZS', 'age_0_14_pct', 'Population ages 0-14', '% of total population'),
    ('SP.POP.1564.TO.ZS', 'age_15_64_pct', 'Population ages 15-64', '% of total population'),
    ('SP.POP.65UP.TO.ZS', 'age_65_plus_pct', 'Population ages 65 and above', '% of total population'),
    ('NY.GDP.MKTP.CD', 'gdp_usd', 'GDP', 'current US$'),
    ('NY.GDP.MKTP.PP.CD', 'gdp_ppp', 'GDP, PPP', 'current international $'),
    ('NY.GDP.PCAP.CD', 'gdp_per_capita_usd', 'GDP per capita', 'current US$'),
    ('NY.GDP.MKTP.KD.ZG', 'gdp_growth_pct', 'GDP growth', 'annual %'),
    ('TX.VAL.MRCH.CD.WT', 'merch_exports_usd', 'Merchandise exports (WTO, via WDI)', 'current US$'),
    ('FP.CPI.TOTL.ZG', 'inflation_pct', 'Inflation, consumer prices', 'annual %'),
    ('SL.UEM.TOTL.ZS', 'unemployment_pct', 'Unemployment (modeled ILO estimate)', '% of labor force'),
    ('IT.NET.USER.ZS', 'internet_users_pct', 'Individuals using the Internet', '% of population'),
    ('IT.CEL.SETS.P2', 'mobile_subs_per100', 'Mobile cellular subscriptions', 'per 100 people'),
    ('SH.MED.BEDS.ZS', 'hospital_beds_per1000', 'Hospital beds', 'per 1,000 people'),
    ('SH.MED.PHYS.ZS', 'physicians_per1000', 'Physicians', 'per 1,000 people'),
    ('SI.POV.GINI', 'gini', 'Gini index', 'index (0-100)'),
]
BANDS = ['0004', '0509', '1014', '1519', '2024', '2529', '3034', '3539', '4044', '4549', '5054', '5559', '6064', '6569', '7074', '7579', '80UP']
AGE_BANDS = [
    (f'SP.POP.{b}.{s[:2].upper()}.5Y', f'age_{b[:2]}_{b[2:].lower()}_{s}_pct',
     f'Population ages {int(b[:2])}-{int(b[2:])}, {s}' if b != '80UP' else f'Population ages 80 and above, {s}', f'% of {s} population')
    for s in ('female', 'male') for b in BANDS
]

WDI = {
    'id': 'wb_wdi',
    'name': 'World Bank World Development Indicators',
    'source': 'World Bank WDI',
    'url': f'{API}/sources/2',
    'license': 'CC BY 4.0',
    'confidence': 'high',
    'fields': [k for _, k, _, _ in CORE] + ['age_<band>_<sex>_pct (17 five-year bands × 2 sexes)'],
    'used_for': 'Country population, economy, health capacity, connectivity and age structure',
    'max_age_days': 120,
    'note': 'Annual values 2000-2025; the API serves the latest observed year per indicator. Five-year age bands are UN WPP '
            'estimates republished in WDI. Gini, hospital beds and physicians are sparse survey series (medium confidence). '
            'Values outside plausible bounds are kept as published and marked low confidence. '
            'Channel Islands (CHI) excluded: no ISO 3166-1 code.',
}
CLASSIFICATION = {
    'id': 'wb_classification',
    'name': 'World Bank country classification (income group, region, lending type)',
    'source': 'World Bank Country API',
    'url': f'{API}/country?format=json',
    'license': 'CC BY 4.0',
    'confidence': 'high',
    'fields': ['iso3', 'wb_income', 'wb_region', 'wb_lending'],
    'used_for': 'Income group and region for persona income bands and country grouping',
    'max_age_days': 400,
    'note': 'Income groups are revised every 1 July; the API returns the current classification without a date, so as_of is the retrieval date.',
}


def _economies(fetch) -> list[dict]:
    _, rows = fetch.json(f'{API}/country?format=json&per_page=400')
    return [c for c in rows if c['region']['value'].strip() != 'Aggregates' and c['id'] not in NON_ISO]


def _compact(page: list) -> list:
    """Keep [iso3, code, year, value] for observed values only; ~10x smaller to cache."""
    if 'message' in page[0]:
        raise ValueError(f"World Bank API error: {page[0]['message']}")
    meta, rows = page[0], page[1] or []
    return [meta, [[r['countryiso3code'], r['indicator']['id'], int(r['date']), r['value']] for r in rows if r['value'] is not None]]


def _series(fetch, codes: list[str]) -> tuple[str, list]:
    out, page, pages, meta = [], 1, 1, {}
    while page <= pages:
        meta, rows = fetch.json(
            f'{API}/country/all/indicator/{";".join(codes)}?source=2&format=json&date={YEARS}&per_page=10000&page={page}',
            transform=_compact)
        pages, page = int(meta['pages']), page + 1
        out += rows
    return meta['lastupdated'], out


def run_wdi(fetch, ctx: dict) -> dict:
    economies = {c['id'] for c in _economies(fetch)}
    info = {code: (key, name, unit) for code, key, name, unit in CORE + AGE_BANDS}
    data, as_of = [], ''
    for group in (CORE, AGE_BANDS):
        last, rows = _series(fetch, [code for code, *_ in group])
        data += rows
        as_of = max(as_of, last)
    p = prov(WDI, as_of, fetch.retrieved)
    rows = [
        {'iso3': iso3, 'indicator': code, 'key': info[code][0], 'name': info[code][1], 'unit': info[code][2], 'year': year,
         'value': value, **p,
         'confidence': 'low' if not plausible(info[code][0], value) else 'medium' if code in SPARSE else 'high'}
        for iso3, code, year, value in data if iso3 in economies
    ]
    return {'tables': {'indicators': rows}, 'as_of': as_of}


def run_classification(fetch, ctx: dict) -> dict:
    economies = _economies(fetch)
    as_of = fetch.retrieved[:10]
    p = prov(CLASSIFICATION, as_of, fetch.retrieved)
    rows = [
        {'iso3': c['id'], 'scheme': scheme, 'code': c[field]['id'], 'label': c[field]['value'].strip(), **p}
        for c in economies
        for scheme, field in (('wb_income', 'incomeLevel'), ('wb_region', 'region'), ('wb_lending', 'lendingType'))
        if c[field]['id']
    ]
    return {'tables': {'country_groups': rows}, 'as_of': as_of}
