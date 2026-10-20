"""Institutional personas (squares on the map): agencies by their seats, companies from the store by HQ."""
from __future__ import annotations

from .modules.base import Institution
from .world import World

# Seats of public bodies (institutional facts).
AGENCIES = {
    'who': ('World Health Organization', 'Geneva', 'CHE', 46.233, 6.134, 'measured, procedural, cites case counts'),
    'cdc': ('US CDC', 'Atlanta', 'USA', 33.799, -84.326, 'technical, cautious'),
    'ecdc': ('ECDC', 'Solna', 'SWE', 59.36, 18.0, 'formal risk assessments'),
    'unhcr': ('UNHCR', 'Geneva', 'CHE', 46.226, 6.137, 'humanitarian, counts the displaced'),
    'ifrc': ('IFRC', 'Geneva', 'CHE', 46.228, 6.137, 'relief logistics, teams and supplies'),
    'imf': ('IMF', 'Washington, D.C.', 'USA', 38.899, -77.044, 'growth revisions, programs'),
    'wto': ('WTO', 'Geneva', 'CHE', 46.224, 6.149, 'rules-based, cites disputes'),
    'ec': ('European Commission', 'Brussels', 'BEL', 50.843, 4.383, 'regulatory, multilateral'),
    'ecb': ('European Central Bank', 'Frankfurt', 'DEU', 50.109, 8.703, 'formal, inflation-focused'),
    'samr': ('China SAMR', 'Beijing', 'CHN', 39.913, 116.39, 'regulatory, terse'),
    'mofcom': ("China Ministry of Commerce", 'Beijing', 'CHN', 39.905, 116.40, 'firm, reciprocal'),
    'reuters': ('Reuters newsroom', 'London', 'GBR', 51.517, -0.105, 'headline register, attribution'),
}
SITES = {
    # Named production/retail sites from public reporting; not in the company store yet.
    'foxconn_zhengzhou': ('Foxconn Zhengzhou plant (line supervisor)', 'Zhengzhou', 'CHN', 34.53, 113.85, 'shifts, quotas, overtime'),
    'bestbuy_ohio': ('Best Buy store manager, Ohio', 'Columbus', 'USA', 39.96, -83.0, 'floor-level: foot traffic, preorders, stock'),
}


def company_like(w: World, *names: str):
    for n in names:
        n = n.lower()
        for cid, c in w.companies.items():
            if cid == n or cid.startswith(n + '-') or n in c.name.lower():
                return c
    return None


def _agency(key: str, role: str) -> Institution:
    label, city, iso3, lat, lon, voice = AGENCIES[key]
    return Institution(f'inst_{key}', label, lat, lon, iso3, role, voice)


def _site(key: str, role: str, company=None) -> Institution:
    label, city, iso3, lat, lon, voice = SITES[key]
    return Institution(f'inst_{key}', label, lat, lon, iso3, role, voice, company_id=company.id if company else None)


def _company(c, role: str, voice: str) -> Institution | None:
    if c is None or c.lat is None:
        return None
    return Institution(f'inst_{c.id}', c.name, c.lat, c.lon, c.country_iso3 or '', role, voice, company_id=c.id, employees=c.employees)


def _government(w: World, iso3: str, label: str, role: str, voice: str) -> Institution | None:
    caps = [c for c in w.cities if c.iso3 == iso3]
    if not caps:
        return None
    cap = max(caps, key=lambda c: (c.capital, c.pop))
    name = w.countries[iso3].name if iso3 in w.countries else iso3
    return Institution(f'inst_{role}_{iso3.lower()}', label.format(country=name), cap.lat, cap.lon, iso3, role, voice)


def build_institutions(w: World, spec, companies: list[str]) -> list[Institution]:
    out: list[Institution | None] = []
    o = spec.origin.iso3 if spec.origin else None
    mod = spec.module
    first = w.companies.get(companies[0]) if companies else None
    if mod == 'launch':
        maker = first or company_like(w, 'apple')
        out.append(_company(maker, 'maker', 'polished, confident, product-first'))
        for n in ('meta', 'samsung', 'sony'):
            c = company_like(w, n)
            if c and (not maker or c.id != maker.id):
                out.append(_company(c, 'competitor', 'competitive, ecosystem talk'))
        out.append(_company(company_like(w, 'tsmc', 'taiwan semiconductor'), 'foundry', 'capacity and yields'))
        out.append(_company(company_like(w, 'foxconn', 'hon hai'), 'assembler', 'volume, lines, lead times'))
        out.append(_site('foxconn_zhengzhou', 'assembler', company_like(w, 'foxconn', 'hon hai')))
        out.append(_site('bestbuy_ohio', 'retailer', company_like(w, 'best buy', 'best-buy')))
        out += [_agency('ec', 'regulator'), _agency('samr', 'regulator')]
    elif mod == 'epidemiology':
        out += [_agency('who', 'health_agency'), _agency('cdc', 'health_agency'), _agency('ecdc', 'health_agency')]
        if o:
            out.append(_government(w, o, 'Ministry of Health, {country}', 'health_ministry', 'official, directive'))
        out.append(_company(company_like(w, 'lufthansa'), 'airline', 'load factors and route suspensions'))
        for n in ('pfizer', 'sanofi', 'astrazeneca', 'moderna'):
            out.append(_company(company_like(w, n), 'vaccine_maker', 'trial timelines and doses'))
    elif mod == 'disaster':
        if o:
            out.append(_government(w, o, 'Disaster agency, {country}', 'civil_protection', 'operational, counts teams and tents'))
            out.append(_government(w, o, 'Government of {country}', 'government', 'official, reassuring'))
        out += [_agency('ifrc', 'relief'), _agency('who', 'health_agency'), _agency('unhcr', 'relief')]
    elif mod == 'trade':
        out += [_agency('ec', 'importer_authority'), _agency('mofcom', 'exporter_authority'), _agency('wto', 'arbiter')]
        for n in ('byd', 'volkswagen', 'tesla', 'saic', 'geely', 'bmw', 'stellantis', 'renault'):
            c = company_like(w, n)
            if c:
                out.append(_company(c, 'company', 'margins, volumes, and lobbying'))
        out.append(_company(company_like(w, 'maersk'), 'shipper', 'routes, rates, and transit days'))
    else:
        if o:
            out.append(_government(w, o, 'Government of {country}', 'government', 'official, measured'))
        out += [_agency('imf', 'markets'), _agency('unhcr', 'relief')]
    for cid in companies:
        c = w.companies.get(cid)
        if c and all(i is None or i.company_id != cid for i in out):
            out.append(_company(c, 'named_company', 'corporate, guarded'))
    out.append(_agency('reuters', 'media'))
    seen, res = set(), []
    for i in out:
        if i and i.id not in seen:
            seen.add(i.id)
            res.append(i)
    return res
