import { existsSync } from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';
import { getCatalog, getCompany, listCountries } from './store';

const hasSnapshot = existsSync(path.resolve(process.cwd(), '../../data/snapshots/LATEST'));

describe.skipIf(!hasSnapshot)('data store (needs `python -m pipeline run`)', () => {
  it('serves a real Apple profile joined from Wikidata, GLEIF and EDGAR', async () => {
    const a = (await getCompany('apple'))!;
    expect(a).toMatchObject({ id: 'apple', qid: 'Q312', ticker: 'AAPL', country_iso3: 'USA', lei: 'HWUPKR0MPOU8FGXBT394' });
    expect(a.provenance.source).toBe('Wikidata');
    expect(a.legal).toMatchObject({ legal_name: 'Apple Inc.', source: 'GLEIF' });
    expect(a.financials.revenue).toMatchObject({ unit: 'USD', source: 'SEC EDGAR', missing_reason: null });
    expect(a.financials.revenue!.value).toBeGreaterThan(2e11);
    expect(a.sites.some((s) => s.kind === 'headquarters' && s.lat !== null)).toBe(true);
    // anything not filled is listed with a reason
    for (const [m, f] of Object.entries(a.financials)) if (f!.value === null) expect(a.missing.map((x) => x.field)).toContain(`financials.${m}`);
  });

  it('resolves QIDs, tickers and unique prefixes; unknown refs are null', async () => {
    expect((await getCompany('Q312'))?.id).toBe('apple');
    expect((await getCompany('aapl'))?.id).toBe('apple');
    expect((await getCompany('meta'))?.qid).toBe('Q380');
    expect(await getCompany('no-such-company-xyz')).toBeNull();
  });

  it('labels a non-SEC filer as missing rather than guessing', async () => {
    const s = (await getCompany('Q20718'))!; // Samsung Electronics: no CIK on Wikidata
    expect(s.cik).toBeNull();
    expect(s.financials.revenue).toMatchObject({ value: null });
    expect(s.missing.find((m) => m.field === 'financials.revenue')?.reason).toMatch(/CIK/);
  });

  it('flags catalog entries stale once they outlive their refresh window', async () => {
    const now = await getCatalog();
    expect(now.find((e) => e.id === 'wb_wdi')).toMatchObject({ license: 'CC BY 4.0', fetch_status: 'live' });
    expect(now.every((e) => e.license && e.confidence && e.snapshot_id)).toBe(true);
    const later = await getCatalog(Date.now() + 4 * 365 * 86_400_000);
    expect(later.filter((e) => e.fetch_status !== 'unavailable').every((e) => e.stale && e.freshness === 'stale')).toBe(true);
  });

  it('lists countries with population and income group', async () => {
    const { countries } = await listCountries();
    expect(countries.length).toBeGreaterThan(230);
    expect(countries.find((c) => c.iso3 === 'VNM')?.population).toBeGreaterThan(9e7);
  });
});
