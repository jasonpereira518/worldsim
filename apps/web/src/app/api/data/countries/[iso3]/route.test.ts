import { existsSync } from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';
import type { CountryProfile } from '@/lib/data/types';
import { GET } from './route';

const hasSnapshot = existsSync(path.resolve(process.cwd(), '../../data/snapshots/LATEST'));
const get = (iso3: string, qs = '') => GET(new Request(`http://localhost/api/data/countries/${iso3}${qs}`), { params: Promise.resolve({ iso3 }) });

describe.skipIf(!hasSnapshot)('GET /api/data/countries/[iso3] (needs `python -m pipeline run`)', () => {
  it('returns real World Bank values for VNM, each with provenance', async () => {
    const res = await get('vnm');
    expect(res.status).toBe(200);
    const c = (await res.json()) as CountryProfile;
    expect(c).toMatchObject({ iso3: 'VNM', iso2: 'VN', name: 'Vietnam' });
    expect(c.snapshot_id).toMatch(/\S/);

    const pop = c.indicators.population;
    expect(pop).toMatchObject({ indicator: 'SP.POP.TOTL', unit: 'people', source: 'World Bank WDI', license: 'CC BY 4.0', confidence: 'high' });
    expect(pop.value).toBeGreaterThan(9e7);
    expect(pop.value).toBeLessThan(1.2e8);
    expect(pop.year).toBeGreaterThanOrEqual(2024);
    expect(pop.as_of).toMatch(/^\d{4}-\d{2}-\d{2}$/);
    expect(pop.retrieved).toMatch(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$/);
    for (const v of Object.values(c.indicators)) for (const k of ['source', 'as_of', 'confidence', 'license', 'retrieved'] as const) expect(v[k], `${v.key}.${k}`).toBeTruthy();

    expect(c.indicators.gdp_usd.value).toBeGreaterThan(1e11);
    expect(c.indicators.life_expectancy.value).toBeGreaterThan(60);
    expect(['LMC', 'UMC']).toContain(c.groups.wb_income.code);
    expect(c.provenance).toMatchObject({ source: 'Natural Earth v5.1.2', license: 'Public domain' });
    expect(c.centroid.lat).toBeGreaterThan(8);
    expect(c.admin1.length).toBeGreaterThanOrEqual(50);

    // 5-year bands rebuilt from shares × sex totals add up to the population of the same year (±2%)
    const bands = c.age_structure!.bands;
    expect(bands).toHaveLength(17);
    const total = bands.reduce((s, b) => s + b.female + b.male, 0);
    expect(Math.abs(total / pop.value - 1)).toBeLessThan(0.02);
    expect(c.series).toBeUndefined();
  });

  it('labels unobserved indicators as missing instead of filling them', async () => {
    const c = (await (await get('VNM', '?series=1')).json()) as CountryProfile;
    expect(c.series!.population.length).toBeGreaterThan(20);
    for (const m of c.missing) expect(c.indicators[m.field.replace('indicators.', '')]).toBeUndefined();
  });

  it('404s an unknown code and 400s a malformed one', async () => {
    expect((await get('ZZZ')).status).toBe(404);
    expect((await get('VN')).status).toBe(400);
  });
});
