import { describe, expect, it } from 'vitest';
import { createRun } from './engine';
import { parsePrompt } from './parse';
import { STATUS_CODES, type Frame, type PersonaStatus } from './types';

const collect = (prompt: string, seed: number) => {
  const run = createRun(parsePrompt(prompt), seed);
  const frames: Frame[] = [];
  for (const f of run.frames()) frames.push(f);
  return { run, frames };
};

describe('mock engine', () => {
  const spec = parsePrompt('A novel H5N1 variant begins human-to-human transmission in Vietnam');
  const { run, frames } = collect(spec.prompt, 7);

  it('produces one frame per step and spreads from the origin', () => {
    expect(frames.length).toBe(Math.ceil(spec.horizon_days / spec.step_days) + 1);
    expect(frames[0].deltas.some((d) => d.id.includes('vnm'))).toBe(true);
    const last = frames[frames.length - 1].metrics;
    expect(last.countries_reached).toBeGreaterThan(20);
    expect(last.ever_affected_pop).toBeGreaterThan(1e8);
  });
  it('is deterministic for a seed and differs across seeds', () => {
    const again = collect(spec.prompt, 7).frames;
    expect(JSON.stringify(again)).toBe(JSON.stringify(frames));
    expect(JSON.stringify(collect(spec.prompt, 8).frames)).not.toBe(JSON.stringify(frames));
  });
  it('never regresses a persona status and keeps bubbles short and explained', () => {
    const rank = (s: PersonaStatus) => STATUS_CODES.indexOf(s);
    const cur = new Map<string, PersonaStatus>();
    for (const f of frames) {
      for (const d of f.deltas) {
        const prev = cur.get(d.id) ?? 'unaware';
        expect(rank(d.status), `${d.id} ${prev}→${d.status}`).toBeGreaterThan(rank(prev));
        cur.set(d.id, d.status);
      }
      for (const b of f.bubbles) {
        expect(b.text.length).toBeLessThanOrEqual(140);
        expect(b.why.metric).toBe('cases');
        expect(run.personas.some((p) => p.id === b.persona_id)).toBe(true);
      }
    }
    expect(frames.some((f) => f.bubbles.length > 0)).toBe(true);
    expect(frames.some((f) => f.flows.length > 0)).toBe(true);
    expect(frames.flatMap((f) => f.events).length).toBeGreaterThan(5);
  });
  it('summarizes with low confidence and no fake intervals', () => {
    const s = run.summary(frames);
    expect(s.headline).toContain('mock');
    expect(s.metrics.every((m) => m.confidence === 'low' && m.low === undefined)).toBe(true);
  });
  it('keeps a disaster local and a launch global', () => {
    const quake = collect('A magnitude 8.1 quake hits Istanbul', 1).frames;
    expect(quake[quake.length - 1].metrics.countries_reached).toBeLessThan(8);
    const launch = collect('Apple launches a $499 AR headset globally next month', 1);
    expect(launch.frames[0].deltas.length).toBeGreaterThan(5);
    expect(launch.frames.flatMap((f) => f.deltas).some((d) => d.status === 'adopted')).toBe(true);
  });
});
