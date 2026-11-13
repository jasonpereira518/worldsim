"""Speech bubbles generated from simulation state. Templates by default; an LLM batch when enabled.

A bubble may only state numbers that appear in its `why` payload, so every bubble traces to a metric change.
"""
from __future__ import annotations

import re

from . import llm
from .util import fmt, unit

PEOPLE = {
    'launch': {
        'aware': ['A ${price} headset? Everyone in {city} is posting the launch video.', 'Saw the launch. In {city} that is {price_share} of a month\'s pay.'],
        'reacting': ['Pre-order is in. If it ships late to {country} I cancel.', 'Tried the demo in {city}. Tempting, but ${price} is ${price}.'],
        'adopted': ['Got mine. {m} of people like me in {city} have one now.', 'Week three with it. My laptop is gathering dust in {city}.'],
        'opposed': ['${price} is {price_share} of a month\'s pay in {city}. Hard pass.', 'Nice demo, wrong price for {country}. I will wait for a cheaper one.'],
    },
    'epidemiology': {
        'aware': ['News says there are cases in {source}. Washing hands more, that is all.', 'Group chat in {city} is all about the new flu.'],
        'reacting': ['{m} here now. I am keeping the kids home this week.', 'Masks are sold out in {city}. Ordered online, overpriced.'],
        'affected': ['Half my team in {city} is out sick. {m}, they say.', 'Clinic in {city} turned us away. Full.', 'Schools are closed again. I cannot work and cannot afford a sitter.'],
        'recovered': ['Back at work in {city}. Still not sure I trust the numbers.', 'Cases are falling here. First normal week in a while.'],
    },
    'disaster': {
        'aware': ['Felt it in {city}. Everyone is outside checking on neighbors.', 'Watching the news from {city}. Calling family near the coast.'],
        'reacting': ['Shaking was strong in {city}. Sleeping in the car tonight.', 'No water in our block of {city} since the quake.'],
        'affected': ['Our building in {city} is cracked. We are in a school gym now.', '{m} in {city}. We left with two bags.'],
        'recovered': ['Moved into a container home outside {city}. It is something.', 'Shop reopened in {city}. Half the street is still rubble.'],
    },
    'trade': {
        'aware': ['Heard the tariff news in {city}. Prices will move.', 'Everyone in {city} is asking what this does to car prices.'],
        'reacting': ['Dealer in {city} quoted more than last month. I am waiting.', 'I was about to buy an EV. Now I am looking at used.'],
        'affected': ['{m} where it hits me in {city}. No room to absorb it.', 'Orders from {partner} dried up. Overtime is gone in {city}.'],
        'opposed': ['This hurts workers in {city}, not the people it targets.', 'Nobody asked us in {country}. Rally on Saturday.'],
    },
    'generic': {
        'aware': ['News from {source}: people in {city} are talking about it.', 'Heard about it in {city}. Watching for now.'],
        'reacting': ['It is changing plans here in {city}. {m}.', 'People in {city} are adjusting. Prices, schedules, everything.'],
        'affected': ['{city} is in the thick of it now: {m}.', 'Daily life in {city} looks different this week.'],
        'recovered': ['Things in {city} are settling. We adapted.'],
        'opposed': ['Not for us in {city}. People here are pushing back.'],
    },
}
INST = {
    'maker': {'aware': ['Announcement is out. The response in {country} is beyond plan.'], 'reacting': ['Pre-orders are open. Every line is running.'],
              'affected': ['{m} shipped. We are expanding the line.']},
    'competitor': {'aware': ['We are watching their launch closely.'], 'reacting': ['Our roadmap holds. Our price is the answer.'],
                   'affected': ['We are cutting our headset price to stay in the game.']},
    'assembler': {'aware': ['New program coming. Hiring notices go up next week.'], 'reacting': ['Second shift approved. Lines ramp next month.'],
                  'affected': ['Overtime every week. Capacity is at {m} of peak.']},
    'foundry': {'aware': ['Wafer starts reserved for the new device.'], 'reacting': ['Allocation is tight but holding.'],
                'affected': ['Running the line at {m} of peak for this program.']},
    'retailer': {'aware': ['Customers already asking when it lands.'], 'reacting': ['Pre-orders are strong. Demo stations are booked.'],
                 'affected': ['Sold out by noon again. Backorders run weeks.']},
    'regulator': {'aware': ['We are reviewing the device under our rules.'], 'reacting': ['Questions sent to the maker on data and safety.'],
                  'affected': ['Review concluded. Sale permitted under conditions.']},
    'health_agency': {'aware': ['Monitoring reports from {source}. No action yet.'], 'reacting': ['Risk assessment raised. Guidance issued today.'],
                      'affected': ['Surge mode. {m} reported in {country}.']},
    'health_ministry': {'aware': ['Cluster under investigation. Contacts traced.'], 'reacting': ['Testing expanded. Schools on alert.'],
                        'affected': ['Hospitals at capacity in parts of {country}.']},
    'airline': {'aware': ['Crews briefed on the new virus.'], 'reacting': ['Screening added on routes to affected airports.'],
                'affected': ['Suspending routes. Load factors collapsed.']},
    'vaccine_maker': {'aware': ['Sequencing the new strain.'], 'reacting': ['Candidate vaccine in development.'], 'affected': ['Scaling fill-finish capacity.']},
    'civil_protection': {'aware': ['Teams deployed to {city}.'], 'reacting': ['Search and rescue in all affected districts.'],
                         'affected': ['{m}. Shelters open across the region.']},
    'government': {'aware': ['Emergency cabinet meeting under way.'], 'reacting': ['State of emergency declared.'], 'affected': ['Reconstruction fund approved.']},
    'relief': {'aware': ['Assessing needs on the ground.'], 'reacting': ['Relief flights arriving.'], 'affected': ['Shelter, water and health teams at full stretch.']},
    'importer_authority': {'aware': ['The measure is published.'], 'reacting': ['Duties are being collected at the border.'], 'affected': ['Monitoring diversion and prices.']},
    'exporter_authority': {'aware': ['We oppose this protectionist measure.'], 'reacting': ['We are preparing countermeasures.'], 'affected': ['Countermeasures are in force.']},
    'arbiter': {'aware': ['A dispute consultation has been requested.'], 'reacting': ['Panel requested.'], 'affected': ['Panel proceedings under way.']},
    'company': {'aware': ['Assessing the impact on our {country} volumes.'], 'reacting': ['Rerouting shipments and reviewing prices.'],
                'affected': ['{m} hit to this line of business.']},
    'shipper': {'aware': ['Customers asking about lane changes.'], 'reacting': ['Volumes shifting to other lanes.'], 'affected': ['Rates moved on the affected lanes.']},
    'markets': {'aware': ['Watching for spillovers.'], 'reacting': ['Revising growth in exposed economies.'], 'affected': ['Emergency financing requests rising.']},
    'media': {'aware': ['Breaking: first reports from {source}.'], 'reacting': ['Live coverage across bureaus.'], 'affected': ['Top story worldwide for days.']},
    'named_company': {'aware': ['We are assessing the situation.'], 'reacting': ['Contingency plans activated.'], 'affected': ['Material impact expected this quarter.']},
}
SENTIMENT = {'aware': 0, 'reacting': -1, 'affected': -1, 'recovered': 1, 'adopted': 1, 'opposed': -1}


def template(module: str, status: str, ctx: dict, pid: str, kind: str, role: str | None) -> str:
    table = INST.get(role or '', INST['named_company']) if kind == 'institution' else PEOPLE.get(module, PEOPLE['generic'])
    options = table.get(status) or PEOPLE['generic'].get(status) or ['{city}: {m}.']
    text = options[int(unit(pid, f'tpl{status}') * len(options))]
    for k, v in ctx.items():
        text = text.replace('{' + k + '}', str(v))
    text = re.sub(r'\{[a-z_]+\}', '', text).strip()
    return text if len(text) <= 140 else text[:137].rstrip() + '…'


SCHEMA = {
    'type': 'object', 'additionalProperties': False, 'required': ['items'],
    'properties': {'items': {'type': 'array', 'items': {
        'type': 'object', 'additionalProperties': False, 'required': ['id', 'text', 'decision', 'emotion'],
        'properties': {'id': {'type': 'string'}, 'text': {'type': 'string'}, 'decision': {'type': 'string'}, 'emotion': {'type': 'string'}}}}},
}
NUM = re.compile(r'\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?')
NUMBER_WORDS = re.compile(r'\b(?:two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|fifteen|twenty|thirty|forty|fifty|sixty|seventy|eighty|'
                          r'ninety|hundreds?|thousands?|dozens?|millions|billions|half|third|quarter|twice|triple|double)\b', re.I)


def _num(n: str) -> str:
    return repr(float(n.replace(',', '')))  # '1,200' == '1200' and '1.50' == '1.5'


def numbers_ok(text: str, allowed: str) -> bool:
    """True when every number in `text` also appears in `allowed`, as digits or words ('twelve', 'thousands', 'half')."""
    have = {_num(n) for n in NUM.findall(allowed)}
    words = {w.lower() for w in NUMBER_WORDS.findall(allowed)}
    return all(_num(n) in have for n in NUM.findall(text)) and all(w.lower() in words for w in NUMBER_WORDS.findall(text))


def llm_batch(items: list[dict], budget: llm.Budget | None, step: int, model: str | None = None) -> dict[str, dict]:
    """items: {id, who, traits, voice, change, numbers, crowd?}. Returns id → {text, decision, emotion} for valid lines."""
    if not items or not llm.enabled():
        return {}
    user = '\n'.join(f'- id={it["id"]}; who={it["who"]}; voice={it["voice"]}; traits={it["traits"]}; change={it["change"]}; numbers={it["numbers"]}'
                     + (f'; crowd stance={it["crowd"]}' if it.get('crowd') else '') for it in items)
    out = llm.structured(llm.prompt('persona_reaction'), user, SCHEMA, model=model or llm.FAST_MODEL, budget=budget, step=step, max_tokens=2000)
    res = {}
    for r in (out or {}).get('items', []):
        src = next((it for it in items if it['id'] == r.get('id')), None)
        text = (r.get('text') or '').strip()
        if src and 0 < len(text) <= 140 and numbers_ok(text, src['numbers'] + ' ' + src['who']):
            res[r['id']] = {'text': text, 'decision': r.get('decision', '')[:60], 'emotion': r.get('emotion', '')[:20]}
    return res


def metric_text(value: float, unit_label: str) -> str:
    if unit_label == '% of segment':
        return f'{value:.1f}%'
    if unit_label.startswith('per 100k'):
        return f'{fmt(value)} cases per 100k'
    if unit_label == 'MMI':
        return f'intensity {value:.1f}'
    if unit_label == '%':
        return f'{value:.1f}%'
    if unit_label == 'index 0-100':
        return f'impact index {value:.0f}'
    return f'{fmt(value)} {unit_label}'
