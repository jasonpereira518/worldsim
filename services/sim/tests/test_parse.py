from worldsim.parse import parse_interventions, parse_prompt, parse_start_date
from worldsim.world import world


def test_reference_prompts():
    w = world()
    a = parse_prompt('A novel H5N1 variant begins human-to-human transmission in Vietnam', w)
    assert (a.event_type, a.module, a.origin.iso3) == ('outbreak', 'epidemiology', 'VNM')
    b = parse_prompt('Apple launches a $499 AR headset worldwide on Dec 1, 2026', w)
    assert (b.event_type, b.module, b.global_) == ('launch', 'launch', True)
    assert next(x.value for x in b.assumptions if x.id == 'price_usd') == 499
    assert next(x.value for x in b.assumptions if x.id == 'launch_date') == '2026-12-01'
    assert b.origin.name.startswith('Apple') or abs(b.origin.lat - 37.33) < 0.1  # HQ from the company store
    c = parse_prompt('The EU imposes a 40% tariff on Chinese EVs', w)
    assert (c.event_type, c.module) == ('policy', 'trade')
    assert next(x.value for x in c.assumptions if x.id == 'tariff_pct') == 40
    d = parse_prompt('A magnitude 8.1 quake hits Istanbul', w)
    assert (d.module, d.origin.name) == ('disaster', 'Istanbul')
    assert next(x.value for x in d.assumptions if x.id == 'magnitude') == 8.1


def test_one_clarifying_question_only_when_needed():
    w = world()
    assert parse_prompt('A massive earthquake strikes', w).clarifying_question
    assert parse_prompt('A massive earthquake strikes', w, {'origin': 'Tokyo'}).origin.name == 'Tokyo'
    assert parse_prompt('A global recession begins', w).clarifying_question is None


def test_dates_and_interventions():
    assert parse_start_date('next month') == '2026-11-20'
    assert parse_start_date('in 10 days') == '2026-10-30'
    iv = parse_interventions('What if borders close on day 10?')
    assert iv[0].kind == 'border_closure' and iv[0].day == 10
    iv = parse_interventions('Rerun with a 20% lower price')
    assert iv[0].kind == 'price_change' and iv[0].value == -20
