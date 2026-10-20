import { describe, expect, it } from 'vitest';
import { PLACES } from './parse';
import { institutionPersonas, peoplePersonas } from './personas';

describe('persona generator', () => {
  it('conserves population exactly and is deterministic', () => {
    const a = peoplePersonas(PLACES);
    const b = peoplePersonas(PLACES);
    expect(a).toEqual(b);
    expect(a.reduce((s, p) => s + p.population_represented, 0)).toBe(PLACES.reduce((s, p) => s + p.pop, 0));
    expect(new Set(a.map((p) => p.id)).size).toBe(a.length);
    expect(a.length).toBeGreaterThan(2500);
    for (const p of a.slice(0, 200)) for (const v of Object.values(p.traits)) { expect(v).toBeGreaterThanOrEqual(0); expect(v).toBeLessThanOrEqual(1); }
  });
  it('selects institutions by event type', () => {
    expect(institutionPersonas('outbreak').map((p) => p.id)).toContain('inst_who');
    expect(institutionPersonas('launch').map((p) => p.id)).not.toContain('inst_who');
    expect(institutionPersonas('launch').every((p) => p.kind === 'institution')).toBe(true);
  });
});
