// Seed ETL for Milestone 0: Natural Earth populated places → data/places.json (+ catalog.json provenance).
// Usage: node scripts/fetch-places.mjs [path-to-local-geojson]   (downloads when no path is given)
import { readFileSync, writeFileSync, mkdirSync } from 'node:fs';

const SOURCE_URL =
  'https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_50m_populated_places_simple.geojson';

const local = process.argv[2];
const text = local ? readFileSync(local, 'utf8') : await (await fetch(SOURCE_URL)).text();
const gj = JSON.parse(text);

const places = gj.features
  .map((f) => f.properties)
  .filter((p) => p.pop_max > 0 && p.adm0_a3 && p.adm0_a3 !== '-99')
  .map((p) => ({
    id: p.ne_id,
    name: p.name,
    country: p.adm0name,
    iso3: p.adm0_a3,
    iso2: p.iso_a2,
    admin1: p.adm1name ?? '',
    lat: +p.latitude.toFixed(4),
    lon: +p.longitude.toFixed(4),
    pop: p.pop_max,
    capital: p.adm0cap === 1,
    hub: p.worldcity === 1 || p.megacity === 1,
  }))
  .sort((a, b) => b.pop - a.pop);

const out = new URL('../data/', import.meta.url);
mkdirSync(out, { recursive: true });
writeFileSync(new URL('places.json', out), JSON.stringify(places));

const catalog = [
  {
    id: 'ne_populated_places_50m',
    name: 'Natural Earth populated places, 1:50m (simple attributes)',
    source: 'Natural Earth v5.1.1',
    url: SOURCE_URL,
    as_of: '2022-05-13',
    retrieved: new Date().toISOString().slice(0, 10),
    license: 'Public domain',
    confidence: 'medium',
    fields: ['id (ne_id)', 'name', 'country', 'iso3', 'iso2', 'admin1', 'lat', 'lon', 'pop (pop_max)', 'capital', 'hub'],
    used_for: 'Milestone 0 mock persona locations and population weights',
    note: 'pop_max is a metro-area estimate (circa 2015). Replaced by WorldPop / UN WUP in Milestone 1.',
  },
];
writeFileSync(new URL('catalog.json', out), JSON.stringify(catalog, null, 2) + '\n');
console.log(`places: ${places.length}, total population: ${places.reduce((s, p) => s + p.pop, 0)}`);
