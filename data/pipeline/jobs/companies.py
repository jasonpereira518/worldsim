"""Companies: Wikidata (selection, identity, ticker, sector, employees, HQ), GLEIF (legal entity), SEC EDGAR (financials).
GLEIF and EDGAR are joined on the LEI and CIK that Wikidata records; nothing is matched by name, so nothing is guessed."""
from __future__ import annotations

import re
import unicodedata
import urllib.parse
from collections import defaultdict
from datetime import date

from ..fetch import SourceUnavailable
from . import need, prov

SPARQL = 'https://query.wikidata.org/sparql'
TARGET = 500
# Reference walkthroughs (AR headset launch, EV tariff, supply chain): always included.
REFERENCE = ['Q312', 'Q380', 'Q20718', 'Q41187', 'Q713418', 'Q463094', 'Q2608329', 'Q156578', 'Q18224', 'Q9325', 'Q533415']

WIKIDATA = {
    'id': 'wikidata_companies',
    'name': 'Wikidata company profiles',
    'source': 'Wikidata',
    'url': 'https://query.wikidata.org/',
    'license': 'CC0 1.0',
    'confidence': 'medium',
    'fields': ['id', 'qid', 'name', 'description', 'industry', 'ticker', 'exchange', 'country_iso3', 'website', 'lei', 'cik',
               'employees', 'employees_as_of', 'headquarters (city, lat/lon)'],
    'used_for': 'Company selection and identity: sector, listing, headcount, headquarters location',
    'max_age_days': 30,
    'note': f'Selection: the {TARGET - len(REFERENCE)} listed, non-dissolved companies with the most employees on Wikidata, plus '
            f'{len(REFERENCE)} reference-walkthrough companies (Apple, Meta, Samsung, Sony, TSMC, Foxconn, BYD, Volkswagen, '
            'Maersk, Lufthansa, Best Buy). A Global 2000-style ranking is not used: those lists are not openly licensed. '
            'Crowd-edited: values can be stale or missing.',
}
GLEIF = {
    'id': 'gleif_lei',
    'name': 'GLEIF Legal Entity Identifier records',
    'source': 'GLEIF',
    'url': 'https://api.gleif.org/api/v1/lei-records',
    'license': 'CC0 1.0',
    'confidence': 'high',
    'fields': ['lei', 'legal_name', 'jurisdiction', 'legal_form', 'entity_status', 'registration_status',
               'headquarters address', 'legal address'],
    'used_for': 'Legal identity and registered headquarters of each company',
    'max_age_days': 30,
    'note': 'Joined on the LEI recorded in Wikidata; companies without one are labeled missing.',
}
EDGAR = {
    'id': 'sec_edgar_companyfacts',
    'name': 'SEC EDGAR XBRL company facts',
    'source': 'SEC EDGAR',
    'url': 'https://data.sec.gov/api/xbrl/companyfacts/',
    'license': 'Public domain (U.S. government work)',
    'confidence': 'high',
    'fields': ['revenue', 'net_income', 'cash', 'debt', 'employees'],
    'used_for': 'Latest annual financials (10-K, 20-F, 40-F) for companies that file with the SEC',
    'max_age_days': 100,
    'note': 'Joined on the CIK recorded in Wikidata. Values are in the reported currency (not converted). "debt" is the '
            'long-term debt concept the filer tags; the XBRL concept is kept on every row. Non-filers are labeled missing.',
}

SELECT_Q = '''SELECT ?c (MAX(?emp) AS ?employees) WHERE {
  ?c wdt:P414 ?exchange ; wdt:P1128 ?emp .
  FILTER NOT EXISTS { ?c wdt:P576 ?dissolved }
} GROUP BY ?c ORDER BY DESC(?employees) ?c LIMIT %d'''

# Flat queries, aggregated in Python: GROUP BY over a large VALUES block overflows the query service's stack.
IDENTITY_Q = '''SELECT ?c ?en ?mul ?description ?lei ?cik ?website WHERE {
  VALUES ?c { %s }
  OPTIONAL { ?c rdfs:label ?en FILTER(LANG(?en) = "en") }
  OPTIONAL { ?c rdfs:label ?mul FILTER(LANG(?mul) = "mul") }
  OPTIONAL { ?c schema:description ?description FILTER(LANG(?description) = "en") }
  OPTIONAL { ?c wdt:P1278 ?lei }
  OPTIONAL { ?c wdt:P5531 ?cik }
  OPTIONAL { ?c wdt:P856 ?website }
}'''

PLACE_Q = '''SELECT ?c ?country ?hq ?coord ?hqCountry WHERE {
  VALUES ?c { %s }
  OPTIONAL { ?c wdt:P17 ?ctry . ?ctry wdt:P298 ?country }
  OPTIONAL { ?c wdt:P159 ?hqItem .
             OPTIONAL { ?hqItem rdfs:label ?hq FILTER(LANG(?hq) = "en") }
             OPTIONAL { ?hqItem wdt:P625 ?coord }
             OPTIONAL { ?hqItem wdt:P17 ?hqCtry . ?hqCtry wdt:P298 ?hqCountry } }
}'''

INDUSTRY_Q = '''SELECT ?c ?industry WHERE {
  VALUES ?c { %s }
  ?c wdt:P452 ?ind . ?ind rdfs:label ?industry FILTER(LANG(?industry) = "en")
}'''

LISTINGS_Q = '''SELECT ?c ?exchange ?exIso ?ticker ?end ?rank WHERE {
  VALUES ?c { %s }
  ?c p:P414 ?st . ?st ps:P414 ?ex ; wikibase:rank ?rank .
  FILTER(?rank != wikibase:DeprecatedRank)
  OPTIONAL { ?st pq:P249 ?ticker }
  OPTIONAL { ?st pq:P582 ?end }
  OPTIONAL { ?ex rdfs:label ?exchange FILTER(LANG(?exchange) = "en") }
  OPTIONAL { ?ex wdt:P17 ?exC . ?exC wdt:P298 ?exIso }
}'''

EMPLOYEES_Q = '''SELECT ?c ?emp ?date WHERE {
  VALUES ?c { %s }
  ?c p:P1128 ?st . ?st ps:P1128 ?emp ; wikibase:rank ?rank .
  FILTER(?rank != wikibase:DeprecatedRank)
  OPTIONAL { ?st pq:P585 ?date }
}'''

SUFFIX = re.compile(r'([,\s]+(inc|incorporated|corp|corporation|co|company|ltd|limited|plc|ag|se|sa|s\.a|nv|n\.v|spa|s\.p\.a'
                    r'|ab|asa|oyj|group|holdings?|kgaa)\.?)+$', re.I)


def slug(name: str) -> str:
    """'Apple Inc.' → 'apple', 'Volkswagen Group' → 'volkswagen'."""
    base = unicodedata.normalize('NFKD', SUFFIX.sub('', name)).encode('ascii', 'ignore').decode().lower()
    return re.sub(r'[^a-z0-9]+', '-', base).strip('-')


def _sparql(fetch, query: str) -> list[dict]:
    """Rows as {var: value}, with entity URIs shortened to QIDs."""
    res = fetch.json(SPARQL, body=urllib.parse.urlencode({'query': query}).encode(),  # POST: 500 QIDs overflow a GET URL
                     headers={'Accept': 'application/sparql-results+json', 'Content-Type': 'application/x-www-form-urlencoded'})
    return [{k: v['value'].rsplit('/', 1)[-1] if v['type'] == 'uri' else v['value'] for k, v in b.items()}
            for b in res['results']['bindings']]


def _point(wkt: str | None) -> tuple[float | None, float | None]:
    m = re.search(r'Point\(([-\d.eE]+) ([-\d.eE]+)\)', wkt or '')
    return (float(m[2]), float(m[1])) if m else (None, None)


def run_wikidata(fetch, ctx: dict) -> dict:
    n = ctx.get('companies_target') or TARGET
    top = [r['c'] for r in _sparql(fetch, SELECT_Q % (n + 50))]
    qids = (REFERENCE + [q for q in top if q not in REFERENCE])[:n]
    # Six queries in total: the query service rate-limits bursts hard (as low as 1 request/minute during incidents).
    values = ' '.join('wd:' + q for q in qids)
    details: dict[str, dict] = defaultdict(dict)
    for query in (IDENTITY_Q, PLACE_Q):
        for r in _sparql(fetch, query % values):  # one row per value combination: keep the smallest per field, like MIN()
            d = details[r['c']]
            for k, v in r.items():
                if k not in d or v < d[k]:
                    d[k] = v
    industries = defaultdict(set)
    for r in _sparql(fetch, INDUSTRY_Q % values):
        industries[r['c']].add(r['industry'])
    listings, employees = defaultdict(list), defaultdict(list)
    for r in _sparql(fetch, LISTINGS_Q % values):
        listings[r['c']].append(r)
    for r in _sparql(fetch, EMPLOYEES_Q % values):
        employees[r['c']].append(r)

    as_of = fetch.retrieved[:10]
    p = prov(WIKIDATA, as_of, fetch.retrieved)
    rows, sites, used = [], [], set()
    for q in qids:
        d = details.get(q, {})
        name = d.get('en') or d.get('mul') or q
        cid = slug(name) or q.lower()
        cid = f'{cid}-{q.lower()}' if cid in used else cid
        used.add(cid)
        country = d.get('hqCountry') or d.get('country')
        # Primary listing: current, has a ticker, on a home-country exchange, preferred rank.
        lst = max(listings[q], default={}, key=lambda r: (
            'end' not in r, 'ticker' in r, r.get('exIso') == country, r.get('rank', '').endswith('PreferredRank'), r.get('exchange', '')))
        emp = max(employees[q], default={}, key=lambda r: (r.get('date', ''), float(r['emp'])))
        lei = (d.get('lei') or '').upper()
        rows.append({
            'id': cid, 'qid': q, 'name': name, 'description': d.get('description'), 'industry': '; '.join(sorted(industries[q])) or None,
            'ticker': lst.get('ticker'), 'exchange': lst.get('exchange'), 'country_iso3': country, 'website': d.get('website'),
            'lei': lei if re.fullmatch(r'[A-Z0-9]{20}', lei) else None,
            'cik': str(int(d['cik'])).zfill(10) if (d.get('cik') or '').isdigit() else None,
            'employees': round(float(emp['emp'])) if emp and float(emp['emp']) > 0 else None,
            'employees_as_of': emp.get('date', '')[:10] or None,
            'reference': q in REFERENCE, **p,
        })
        lat, lon = _point(d.get('coord'))
        if d.get('hq'):
            sites.append({'company_id': cid, 'kind': 'headquarters', 'name': None, 'address': None, 'city': d['hq'],
                          'region': None, 'country_iso3': d.get('hqCountry') or country, 'lat': lat, 'lon': lon, **p})
    return {'tables': {'companies': rows, 'company_sites': sites}, 'as_of': as_of, 'ctx': {'companies': rows}}


def _gleif_compact(page: dict) -> list[dict]:
    out = []
    for r in page['data']:
        e, reg = r['attributes']['entity'], r['attributes']['registration']
        out.append({'lei': r['id'], 'legal_name': e['legalName']['name'], 'jurisdiction': e.get('jurisdiction'),
                    'legal_form': (e.get('legalForm') or {}).get('id'), 'entity_status': e.get('status'),
                    'registration_status': reg.get('status'), 'last_update': reg.get('lastUpdateDate'),
                    'headquarters': e.get('headquartersAddress'), 'legal_address': e.get('legalAddress')})
    return out


def run_gleif(fetch, ctx: dict) -> dict:
    companies = need(ctx, 'companies', WIKIDATA['id'])
    iso2_to_iso3 = ctx.get('iso2_to_iso3', {})
    leis = sorted({c['lei'] for c in companies if c['lei']})
    records = {}
    for i in range(0, len(leis), 100):
        url = 'https://api.gleif.org/api/v1/lei-records?' + urllib.parse.urlencode({'filter[lei]': ','.join(leis[i:i + 100]), 'page[size]': 100})
        records |= {r['lei']: r for r in fetch.json(url, transform=_gleif_compact) or []}
    retrieved = fetch.retrieved or ctx['run_started']
    legal, sites = [], []
    for c in companies:
        r = records.get(c['lei'])
        if not r:
            continue  # no LEI on Wikidata, or one GLEIF does not know: the API reports legal identity as missing
        p = prov(GLEIF, (r['last_update'] or retrieved)[:10], retrieved)
        legal.append({'company_id': c['id'], **{k: r[k] for k in ('lei', 'legal_name', 'jurisdiction', 'legal_form',
                                                                   'entity_status', 'registration_status')}, **p})
        for kind in ('headquarters', 'legal_address'):
            a = r[kind]
            if a:
                sites.append({'company_id': c['id'], 'kind': kind, 'name': r['legal_name'],
                              'address': ', '.join(a.get('addressLines') or []) or None, 'city': a.get('city'),
                              'region': a.get('region'), 'country_iso3': iso2_to_iso3.get(a.get('country')),
                              'lat': None, 'lon': None, **p})
    as_of = max((r['as_of'] for r in legal), default=retrieved[:10])
    return {'tables': {'company_legal': legal, 'company_sites': sites}, 'as_of': as_of}


ANNUAL_FORMS = {'10-K', '10-K/A', '20-F', '20-F/A', '40-F', '40-F/A'}
METRICS = {  # metric → (period kind, concepts in priority order)
    'revenue': ('duration', [('us-gaap', 'Revenues'), ('us-gaap', 'RevenueFromContractWithCustomerExcludingAssessedTax'),
                             ('us-gaap', 'RevenueFromContractWithCustomerIncludingAssessedTax'), ('us-gaap', 'SalesRevenueNet'),
                             ('ifrs-full', 'Revenue')]),
    'net_income': ('duration', [('us-gaap', 'NetIncomeLoss'), ('us-gaap', 'ProfitLoss'),
                                ('ifrs-full', 'ProfitLossAttributableToOwnersOfParent'), ('ifrs-full', 'ProfitLoss')]),
    'cash': ('instant', [('us-gaap', 'CashAndCashEquivalentsAtCarryingValue'),
                         ('us-gaap', 'CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents'),
                         ('ifrs-full', 'CashAndCashEquivalents')]),
    'debt': ('instant', [('us-gaap', 'LongTermDebt'), ('us-gaap', 'LongTermDebtNoncurrent'),
                         ('us-gaap', 'LongTermDebtAndCapitalLeaseObligations'), ('ifrs-full', 'LongtermBorrowings'),
                         ('ifrs-full', 'NoncurrentPortionOfNoncurrentBorrowings')]),
    'employees': ('instant', [('dei', 'EntityNumberOfEmployees')]),
}


def pick(facts: dict, kind: str, concepts: list[tuple[str, str]]) -> dict | None:
    """Latest annual fact across the concepts. Ties on period end go to the reporting currency (the unit with
    the most facts, so TSMC stays in TWD rather than its USD convenience translation), then concept priority, then the latest filing."""
    best = None
    for prio, (tax, concept) in enumerate(concepts):
        units = facts.get(tax, {}).get(concept, {}).get('units', {})
        main = max(units, key=lambda u: len(units[u]), default=None)
        for unit, items in units.items():
            for f in items:
                if f.get('form') not in ANNUAL_FORMS:
                    continue
                if kind == 'duration' and not ('start' in f and 350 <= (date.fromisoformat(f['end']) - date.fromisoformat(f['start'])).days <= 380):
                    continue
                key = (f['end'], unit == main, -prio, f['filed'])
                if best is None or key > best[0]:
                    best = (key, {'value': f['val'], 'unit': unit, 'period_start': f.get('start'), 'period_end': f['end'],
                                  'form': f['form'], 'filed': f['filed'], 'concept': f'{tax}:{concept}'})
    return best[1] if best else None


def _edgar_compact(doc: dict) -> dict:
    return {m: pick(doc.get('facts', {}), kind, concepts) for m, (kind, concepts) in METRICS.items()}


def run_edgar(fetch, ctx: dict) -> dict:
    companies = need(ctx, 'companies', WIKIDATA['id'])
    found: dict[str, dict | None] = {}
    reasons: dict[str, str] = {}
    for c in companies:
        if not c['cik']:
            reasons[c['id']] = 'no SEC CIK on Wikidata (not an SEC registrant, or not linked)'
            continue
        try:
            found[c['id']] = fetch.json(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{c['cik']}.json", transform=_edgar_compact)
        except SourceUnavailable:
            fetch.status = 'partial'
            reasons[c['id']] = 'SEC EDGAR did not respond and no cached copy exists'
            continue
        if found[c['id']] is None:
            reasons[c['id']] = f"CIK {c['cik']} has no XBRL company facts"
    retrieved = fetch.retrieved or ctx['run_started']
    rows = []
    for c in companies:
        facts = found.get(c['id']) or {}
        for m, (_, concepts) in METRICS.items():
            v = facts.get(m)
            if v:
                rows.append({'company_id': c['id'], 'metric': m, 'value': v['value'], 'unit': v['unit'], 'period_start': v['period_start'],
                             'period_end': v['period_end'], 'form': v['form'], 'concept': v['concept'], 'missing_reason': None,
                             **prov(EDGAR, v['filed'], retrieved)})
            else:
                reason = reasons.get(c['id']) or 'no annual-filing fact for ' + ' / '.join(f'{t}:{n}' for t, n in concepts)
                rows.append({'company_id': c['id'], 'metric': m, 'value': None, 'unit': None, 'period_start': None, 'period_end': None,
                             'form': None, 'concept': None, 'missing_reason': reason, **prov(EDGAR, retrieved[:10], retrieved)})
    as_of = max((r['as_of'] for r in rows if r['value'] is not None), default=retrieved[:10])
    return {'tables': {'company_financials': rows}, 'as_of': as_of}
