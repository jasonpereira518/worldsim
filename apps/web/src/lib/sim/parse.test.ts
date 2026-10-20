import { describe, expect, it } from 'vitest';
import { parsePrompt, parseStartDate } from './parse';

describe('parsePrompt', () => {
  it('classifies the four reference prompts', () => {
    const a = parsePrompt('A novel H5N1 variant begins human-to-human transmission in Vietnam');
    expect(a.event_type).toBe('outbreak');
    expect(a.origin?.iso3).toBe('VNM');
    expect(a.clarifying_question).toBeUndefined();

    const b = parsePrompt('Apple launches a $499 AR headset globally next month');
    expect(b.event_type).toBe('launch');
    expect(b.global).toBe(true);
    expect(b.assumptions.find((x) => x.id === 'price')?.value).toBe(499);
    expect(b.start_date).toBe('2026-11-20');

    const c = parsePrompt('The EU imposes a 40% tariff on Chinese EVs');
    expect(c.event_type).toBe('policy');
    expect(c.assumptions.find((x) => x.id === 'rate')?.value).toBe(40);
    expect(c.origin?.country).toMatch(/China|Belgium/);

    const d = parsePrompt('A magnitude 8.1 quake hits Istanbul');
    expect(d.event_type).toBe('disaster');
    expect(d.origin?.name).toBe('Istanbul');
    expect(d.assumptions.find((x) => x.id === 'magnitude')?.value).toBe(8.1);
  });
  it('asks one question when a local event has no place', () => {
    const s = parsePrompt('A massive earthquake strikes');
    expect(s.clarifying_question).toBeDefined();
    expect(parsePrompt('A massive earthquake strikes', { origin: 'Tokyo' }).origin?.name).toBe('Tokyo');
  });
  it('parses explicit and relative dates against t0', () => {
    expect(parseStartDate('launch on Dec 1, 2026')).toBe('2026-12-01');
    expect(parseStartDate('in 10 days')).toBe('2026-10-30');
    expect(parseStartDate('no date here')).toBe('2026-10-20');
  });
});
