// Lookup-only gazetteer: Natural Earth 1:10m populated places → data/gazetteer.json.
// Used by the sim's place lookup (parse.find_place) to find epicenters and origins that the 1:50m seed lacks
// (Izmit, Kahramanmaras, Kumamoto). It does not place personas: places.json still does.
// Usage: node scripts/fetch-gazetteer.mjs [path-to-local-geojson]   (downloads when no path is given)
import { readFileSync, writeFileSync } from 'node:fs';

const SOURCE_URL =
  'https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_10m_populated_places_simple.geojson';
const MIN_POP = 50000; // smaller towns add little and their names collide with ordinary words

const local = process.argv[2];
const text = local ? readFileSync(local, 'utf8') : await (await fetch(SOURCE_URL)).text();
const places = JSON.parse(text)
  .features.map((f) => f.properties)
  .filter((p) => p.pop_max >= MIN_POP && p.adm0_a3 && p.adm0_a3 !== '-99')
  .map((p) => ({
    id: p.ne_id,
    name: p.name,
    ...(p.nameascii && p.nameascii !== p.name ? { ascii: p.nameascii } : {}),
    country: p.adm0name,
    iso3: p.adm0_a3,
    admin1: p.adm1name ?? '',
    lat: +p.latitude.toFixed(4),
    lon: +p.longitude.toFixed(4),
    pop: p.pop_max,
  }))
  .sort((a, b) => b.pop - a.pop);

const source = {
  id: 'ne_populated_places_10m',
  name: 'Natural Earth populated places, 1:10m (simple attributes)',
  source: 'Natural Earth v5.1.1',
  url: SOURCE_URL,
  retrieved: new Date().toISOString().slice(0, 10),
  license: 'Public domain',
  filter: `pop_max >= ${MIN_POP}`,
  used_for: 'Place lookup only (scenario origins and epicenters); not persona placement',
};
writeFileSync(new URL('../data/gazetteer.json', import.meta.url), JSON.stringify({ source, places }));
console.log(`gazetteer: ${places.length} places`);
