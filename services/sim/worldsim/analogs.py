"""Event-history library: past analogs with structured outcomes and sources. Used to choose generic-module
parameters, cited in reports, and as the reference class for scale (magnitude) comparisons.

`metrics` are keyed by the outcome keys of the module named in `module`, so a run's outcome can be set beside the
historical value; `definition` says what the number counts (reported vs modeled deaths, etc.). Retrieval is keyword
scoring here; the data phase replaces `search`/`get` with an event database without changing their signatures."""
from __future__ import annotations

ANALOGS = [
    {'id': 'covid19', 'name': 'COVID-19 pandemic (2020-)', 'type': 'outbreak', 'module': 'epidemiology', 'reach': 'global',
     'keywords': ['virus', 'pandemic', 'respiratory', 'covid', 'sars'],
     'outcomes': 'Over 7 million deaths reported to WHO by 2024; reached every region within about three months of the first reports.',
     'metrics': {'deaths': 7.0e6}, 'definition': 'deaths reported to WHO by 2024; excess-mortality estimates are several times higher',
     'source': 'WHO COVID-19 dashboard'},
    {'id': 'sars2003', 'name': 'SARS (2002-2003)', 'type': 'outbreak', 'module': 'epidemiology', 'reach': 'global',
     'keywords': ['sars', 'coronavirus', 'respiratory'],
     'outcomes': '8,096 probable cases and 774 deaths in 29 countries.', 'metrics': {'deaths': 774, 'reported': 8096, 'countries': 29},
     'definition': 'probable cases and deaths; countries reporting probable cases', 'source': 'WHO summary table, 2004'},
    {'id': 'h1n1_2009', 'name': '2009 H1N1 influenza pandemic', 'type': 'outbreak', 'module': 'epidemiology', 'reach': 'global',
     'keywords': ['influenza', 'flu', 'h1n1', 'h5n1', 'avian', 'variant'],
     'outcomes': '18,449 laboratory-confirmed deaths; modeled 151,700-575,400 deaths in the first year.', 'metrics': {'deaths': 284500},
     'definition': 'modeled first-year deaths, central estimate (laboratory-confirmed deaths were 18,449)', 'source': 'WHO; Dawood et al. (2012), Lancet Infect Dis'},
    {'id': 'ebola2014', 'name': 'West Africa Ebola epidemic (2014-2016)', 'type': 'outbreak', 'module': 'epidemiology', 'reach': 'multi_country',
     'keywords': ['ebola', 'hemorrhagic'],
     'outcomes': '28,600 cases and 11,325 deaths, concentrated in Guinea, Liberia and Sierra Leone.', 'metrics': {'deaths': 11325, 'reported': 28600, 'countries': 10},
     'definition': 'reported cases and deaths; countries with at least one case', 'source': 'WHO situation report, 2016'},
    {'id': 'gfc2008', 'name': 'Global financial crisis (2008-2009)', 'type': 'finance', 'module': 'generic', 'reach': 'global',
     'keywords': ['bank', 'crash', 'default', 'credit', 'recession', 'lehman'],
     'outcomes': 'US unemployment peaked at 10.0% in October 2009.', 'metrics': {}, 'definition': '', 'source': 'US Bureau of Labor Statistics'},
    {'id': 'tohoku2011', 'name': 'Tōhoku earthquake and tsunami (2011)', 'type': 'disaster', 'module': 'disaster', 'reach': 'regional',
     'keywords': ['earthquake', 'tsunami', 'quake', 'japan', 'nuclear'],
     'outcomes': 'About 18,500 dead and missing; Fukushima Daiichi accident.', 'metrics': {'deaths': 18500},
     'definition': 'dead and missing, mostly from the tsunami (not modeled by the earthquake module)', 'source': 'Japan National Police Agency'},
    {'id': 'kahramanmaras2023', 'name': 'Kahramanmaraş earthquakes (2023)', 'type': 'disaster', 'module': 'disaster', 'reach': 'multi_country',
     'keywords': ['earthquake', 'quake', 'turkey', 'türkiye', 'syria'],
     'outcomes': '50,783 deaths in Türkiye (AFAD) plus several thousand in Syria.', 'metrics': {'deaths': 50783},
     'definition': 'deaths in Türkiye only', 'source': 'AFAD'},
    {'id': 'izmit1999', 'name': 'İzmit earthquake (1999)', 'type': 'disaster', 'module': 'disaster', 'reach': 'regional',
     'keywords': ['earthquake', 'quake', 'turkey', 'türkiye', 'istanbul', 'marmara'],
     'outcomes': 'Mw 7.6; 17,127 deaths.', 'metrics': {'deaths': 17127}, 'definition': 'official death toll', 'source': 'Turkish government via USGS'},
    {'id': 'gorkha2015', 'name': 'Gorkha earthquake, Nepal (2015)', 'type': 'disaster', 'module': 'disaster', 'reach': 'multi_country',
     'keywords': ['earthquake', 'quake', 'nepal', 'kathmandu', 'himalaya'],
     'outcomes': 'Mw 7.8; 8,964 deaths in Nepal.', 'metrics': {'deaths': 8964}, 'definition': 'deaths in Nepal', 'source': 'Government of Nepal'},
    {'id': 'haiti2010', 'name': 'Haiti earthquake (2010)', 'type': 'disaster', 'module': 'disaster', 'reach': 'national',
     'keywords': ['earthquake', 'quake', 'haiti', 'port-au-prince', 'caribbean'],
     'outcomes': 'Mw 7.0; about 160,000 deaths (survey estimate; official figures were higher and disputed).', 'metrics': {'deaths': 160000},
     'definition': 'household-survey estimate', 'source': 'Kolbe et al. (2010) household survey'},
    {'id': 'kumamoto2016', 'name': 'Kumamoto earthquakes (2016)', 'type': 'disaster', 'module': 'disaster', 'reach': 'regional',
     'keywords': ['earthquake', 'quake', 'japan', 'kyushu', 'kumamoto'],
     'outcomes': 'Mw 7.0; 273 deaths including disaster-related deaths.', 'metrics': {'deaths': 273},
     'definition': 'direct and disaster-related deaths', 'source': 'Japan Cabinet Office'},
    {'id': 'wenchuan2008', 'name': 'Wenchuan earthquake (2008)', 'type': 'disaster', 'module': 'disaster', 'reach': 'regional',
     'keywords': ['earthquake', 'quake', 'china', 'sichuan', 'wenchuan'],
     'outcomes': 'Mw 7.9; 87,587 dead and missing.', 'metrics': {'deaths': 87587}, 'definition': 'dead and missing', 'source': 'Government of China'},
    {'id': 'suez2021', 'name': 'Suez Canal blockage by Ever Given (2021)', 'type': 'supply_chain', 'module': 'trade', 'reach': 'global',
     'keywords': ['canal', 'shipping', 'suez', 'chokepoint', 'blockage'],
     'outcomes': 'Six-day closure; an estimated $9.6B of trade held up per day.', 'metrics': {}, 'definition': '', 'source': "Lloyd's List estimate"},
    {'id': 'iphone2007', 'name': 'Original iPhone launch (2007)', 'type': 'launch', 'module': 'launch', 'reach': 'multi_country',
     'keywords': ['phone', 'smartphone', 'apple', 'launch', 'device'],
     'outcomes': 'Launched at $499-599; about 6.1 million units sold before the iPhone 3G replaced it.', 'metrics': {'units_m': 6.1},
     'definition': 'units sold over its roughly one-year life', 'source': 'Apple financial filings'},
    {'id': 'visionpro2024', 'name': 'Apple Vision Pro launch (2024)', 'type': 'launch', 'module': 'launch', 'reach': 'multi_country',
     'keywords': ['headset', 'ar', 'vr', 'apple', 'spatial'],
     'outcomes': 'Launched at $3,499 in the US; third-party estimates put first-year shipments below 500,000.', 'metrics': {'units_m': 0.5},
     'definition': 'third-party upper estimate of first-year shipments', 'source': 'IDC estimate (not company-reported)'},
    {'id': 'model3_2016', 'name': 'Tesla Model 3 reservations (2016)', 'type': 'launch', 'module': 'launch', 'reach': 'global',
     'keywords': ['ev', 'electric', 'tesla', 'car', 'reservation'],
     'outcomes': 'About 325,000 reservations in the first week.', 'metrics': {}, 'definition': 'reservations, not deliveries', 'source': 'Tesla'},
    {'id': 'gdpr2018', 'name': 'GDPR enforcement (2018)', 'type': 'policy', 'module': 'trade', 'reach': 'global',
     'keywords': ['regulation', 'privacy', 'eu', 'data'],
     'outcomes': 'In force from 25 May 2018 across the EU and EEA; global firms changed data practices worldwide.', 'metrics': {}, 'definition': '',
     'source': 'European Commission'},
    {'id': 'us_tariffs2018', 'name': 'US-China tariffs (2018-2019)', 'type': 'policy', 'module': 'trade', 'reach': 'multi_country',
     'keywords': ['tariff', 'trade war', 'china', 'duties'],
     'outcomes': 'Near-complete pass-through of US tariffs to US import prices.', 'metrics': {}, 'definition': '',
     'source': 'Amiti, Redding & Weinstein (2019), JEP'},
    {'id': 'brexit2016', 'name': 'Brexit referendum (2016)', 'type': 'election', 'module': 'generic', 'reach': 'national',
     'keywords': ['referendum', 'vote', 'brexit', 'eu', 'uk'],
     'outcomes': 'Sterling fell about 8% against the dollar the next day.', 'metrics': {}, 'definition': '', 'source': 'Bank of England'},
]
_BY_ID = {a['id']: a for a in ANALOGS}


def search(query: str, event_type: str | None = None, k: int = 3) -> list[dict]:
    """Analogs ranked by event-type match (+2) and keyword hits in the query."""
    text = query.lower()
    scored = []
    for a in ANALOGS:
        score = (2 if a['type'] == event_type else 0) + sum(1 for w in a['keywords'] if w in text)
        if score:
            scored.append((score, a))
    return [a for _, a in sorted(scored, key=lambda x: -x[0])[:k]]


def get(analog_id: str) -> dict | None:
    return _BY_ID.get(analog_id)


def analogs_for(spec, k: int = 3) -> list[dict]:
    return search(spec.prompt, spec.event_type, k)
