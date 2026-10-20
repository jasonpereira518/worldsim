"""Event-history library: past analogs with structured outcomes and sources. Used to choose generic-module
parameters and cited in reports. Retrieval is keyword-based here; pgvector retrieval replaces it with the store."""
from __future__ import annotations

ANALOGS = [
    {'id': 'covid19', 'name': 'COVID-19 pandemic (2020-)', 'type': 'outbreak', 'keywords': ['virus', 'pandemic', 'respiratory', 'covid', 'sars'],
     'outcomes': 'Over 7 million deaths reported to WHO by 2024; reached every region within about three months of the first reports.',
     'source': 'WHO COVID-19 dashboard'},
    {'id': 'sars2003', 'name': 'SARS (2002-2003)', 'type': 'outbreak', 'keywords': ['sars', 'coronavirus', 'respiratory'],
     'outcomes': '8,096 probable cases and 774 deaths in 29 countries.', 'source': 'WHO summary table, 2004'},
    {'id': 'h1n1_2009', 'name': '2009 H1N1 influenza pandemic', 'type': 'outbreak', 'keywords': ['influenza', 'flu', 'h1n1', 'h5n1', 'avian', 'variant'],
     'outcomes': '18,449 laboratory-confirmed deaths; modeled 151,700-575,400 deaths in the first year.', 'source': 'WHO; Dawood et al. (2012), Lancet Infect Dis'},
    {'id': 'ebola2014', 'name': 'West Africa Ebola epidemic (2014-2016)', 'type': 'outbreak', 'keywords': ['ebola', 'hemorrhagic'],
     'outcomes': '28,600 cases and 11,325 deaths, concentrated in Guinea, Liberia and Sierra Leone.', 'source': 'WHO situation report, 2016'},
    {'id': 'gfc2008', 'name': 'Global financial crisis (2008-2009)', 'type': 'finance', 'keywords': ['bank', 'crash', 'default', 'credit', 'recession', 'lehman'],
     'outcomes': 'US unemployment peaked at 10.0% in October 2009.', 'source': 'US Bureau of Labor Statistics'},
    {'id': 'tohoku2011', 'name': 'Tōhoku earthquake and tsunami (2011)', 'type': 'disaster', 'keywords': ['earthquake', 'tsunami', 'quake', 'japan', 'nuclear'],
     'outcomes': 'About 18,500 dead and missing; Fukushima Daiichi accident.', 'source': 'Japan National Police Agency'},
    {'id': 'kahramanmaras2023', 'name': 'Kahramanmaraş earthquakes (2023)', 'type': 'disaster', 'keywords': ['earthquake', 'quake', 'turkey', 'türkiye', 'syria'],
     'outcomes': '50,783 deaths in Türkiye (AFAD) plus several thousand in Syria.', 'source': 'AFAD'},
    {'id': 'suez2021', 'name': 'Suez Canal blockage by Ever Given (2021)', 'type': 'supply_chain', 'keywords': ['canal', 'shipping', 'suez', 'chokepoint', 'blockage'],
     'outcomes': 'Six-day closure; an estimated $9.6B of trade held up per day.', 'source': "Lloyd's List estimate"},
    {'id': 'iphone2007', 'name': 'Original iPhone launch (2007)', 'type': 'launch', 'keywords': ['phone', 'smartphone', 'apple', 'launch', 'device'],
     'outcomes': 'Launched at $499-599; about 6.1 million units sold before the iPhone 3G replaced it.', 'source': 'Apple financial filings'},
    {'id': 'visionpro2024', 'name': 'Apple Vision Pro launch (2024)', 'type': 'launch', 'keywords': ['headset', 'ar', 'vr', 'apple', 'spatial'],
     'outcomes': 'Launched at $3,499 in the US; third-party estimates put first-year shipments below 500,000.', 'source': 'IDC estimate (not company-reported)'},
    {'id': 'model3_2016', 'name': 'Tesla Model 3 reservations (2016)', 'type': 'launch', 'keywords': ['ev', 'electric', 'tesla', 'car', 'reservation'],
     'outcomes': 'About 325,000 reservations in the first week.', 'source': 'Tesla'},
    {'id': 'gdpr2018', 'name': 'GDPR enforcement (2018)', 'type': 'policy', 'keywords': ['regulation', 'privacy', 'eu', 'data'],
     'outcomes': 'In force from 25 May 2018 across the EU and EEA; global firms changed data practices worldwide.', 'source': 'European Commission'},
    {'id': 'us_tariffs2018', 'name': 'US-China tariffs (2018-2019)', 'type': 'policy', 'keywords': ['tariff', 'trade war', 'china', 'duties'],
     'outcomes': 'Near-complete pass-through of US tariffs to US import prices.', 'source': 'Amiti, Redding & Weinstein (2019), JEP'},
    {'id': 'brexit2016', 'name': 'Brexit referendum (2016)', 'type': 'election', 'keywords': ['referendum', 'vote', 'brexit', 'eu', 'uk'],
     'outcomes': 'Sterling fell about 8% against the dollar the next day.', 'source': 'Bank of England'},
]


def analogs_for(spec, k: int = 3) -> list[dict]:
    text = spec.prompt.lower()
    scored = []
    for a in ANALOGS:
        score = (2 if a['type'] == spec.event_type else 0) + sum(1 for w in a['keywords'] if w in text)
        if score:
            scored.append((score, a))
    return [a for _, a in sorted(scored, key=lambda x: -x[0])[:k]]
