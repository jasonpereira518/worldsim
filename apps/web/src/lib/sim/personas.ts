// Persona generator. M0: segments per place with population-conserving shares; traits are deterministic per id.
// M1 draws segments from real age/income/urbanization distributions instead of these mock shares.
import type { EventType, Persona, Place } from './types';
import { clamp01, unit } from './prng';

type Traits = Persona['traits'];
interface Segment {
  key: string;
  label: string;
  share: number;
  demographics: Persona['demographics'];
  bias: Partial<Traits>;
  voice: string;
}

const seg = (key: string, label: string, share: number, d: Partial<Persona['demographics']>, bias: Partial<Traits>, voice: string): Segment => ({
  key, label, share, bias, voice,
  demographics: { age_band: '25-54', income_band: 'middle', occupation_class: 'services', education: 'secondary', urban_rural: 'urban', ...d },
});

const BIG: Segment[] = [
  seg('commuters', 'Urban commuters', 0.45, {}, { media_exposure: 0.15, social_connectedness: 0.1 }, 'practical, time-pressed, talks about work and transport'),
  seg('students', 'Students', 0.2, { age_band: '18-24', income_band: 'low', occupation_class: 'student', education: 'tertiary (in progress)' }, { tech_adoption: 0.25, price_sensitivity: 0.3, media_exposure: 0.2, risk_tolerance: 0.15 }, 'online-first, blunt, price-aware'),
  seg('owners', 'Small-business owners', 0.2, { age_band: '35-64', income_band: 'middle', occupation_class: 'self-employed' }, { price_sensitivity: 0.1, institutional_trust: -0.1 }, 'thinks in cash flow and customers'),
  seg('retirees', 'Retirees', 0.15, { age_band: '65+', income_band: 'fixed', occupation_class: 'retired' }, { risk_tolerance: -0.25, tech_adoption: -0.25, institutional_trust: 0.1, media_exposure: -0.1 }, 'cautious, relies on TV news and family'),
];
const MID: Segment[] = [
  seg('residents', 'Working residents', 0.55, {}, {}, 'plain-spoken, local, focused on prices and daily routine'),
  seg('traders', 'Market traders and drivers', 0.3, { income_band: 'low-middle', occupation_class: 'informal', education: 'primary-secondary' }, { price_sensitivity: 0.25, institutional_trust: -0.15, social_connectedness: 0.2 }, 'talks about supply, prices, and rumors'),
  seg('retirees', 'Retirees', 0.15, { age_band: '65+', income_band: 'fixed', occupation_class: 'retired' }, { risk_tolerance: -0.25, tech_adoption: -0.25 }, 'cautious, relies on radio and neighbors'),
];
const SMALL: Segment[] = [
  seg('residents', 'Town residents', 0.7, { urban_rural: 'peri-urban' }, { media_exposure: -0.1 }, 'local, concrete, family-first'),
  seg('farmers', 'Farmers and traders', 0.3, { income_band: 'low', occupation_class: 'agriculture', education: 'primary', urban_rural: 'rural' }, { institutional_trust: -0.1, tech_adoption: -0.2, price_sensitivity: 0.2 }, 'talks about harvests, roads, and prices'),
];

// Mock proxy for income level until World Bank classification lands in M1.
const HIGH_INCOME = new Set(['USA', 'CAN', 'GBR', 'IRL', 'FRA', 'DEU', 'NLD', 'BEL', 'LUX', 'CHE', 'AUT', 'DNK', 'SWE', 'NOR', 'FIN', 'ISL', 'ITA', 'ESP', 'PRT', 'GRC', 'CZE', 'POL', 'EST', 'LVA', 'LTU', 'SVN', 'SVK', 'HUN', 'HRV', 'JPN', 'KOR', 'TWN', 'SGP', 'HKG', 'AUS', 'NZL', 'ISR', 'ARE', 'QAT', 'KWT', 'SAU', 'BHR', 'OMN', 'CHL', 'URY', 'PAN']);

const TRAIT_KEYS: (keyof Traits)[] = ['risk_tolerance', 'institutional_trust', 'media_exposure', 'price_sensitivity', 'tech_adoption', 'social_connectedness'];

function traitsFor(id: string, bias: Partial<Traits>, highIncome: boolean): Traits {
  const t = {} as Traits;
  for (const k of TRAIT_KEYS) {
    let v = 0.25 + 0.5 * unit(id, k) + (bias[k] ?? 0);
    if (k === 'tech_adoption' || k === 'media_exposure') v += highIncome ? 0.1 : -0.1;
    if (k === 'price_sensitivity') v += highIncome ? -0.15 : 0.1;
    t[k] = +clamp01(v).toFixed(2);
  }
  return t;
}

export function peoplePersonas(places: Place[]): Persona[] {
  const out: Persona[] = [];
  for (const p of places) {
    const segments = p.pop >= 5_000_000 ? BIG : p.pop >= 1_000_000 ? MID : SMALL;
    const high = HIGH_INCOME.has(p.iso3);
    let remaining = p.pop;
    segments.forEach((s, i) => {
      const pop = i === segments.length - 1 ? remaining : Math.round(p.pop * s.share);
      remaining -= pop;
      const id = `persona_${p.iso3}_${p.id}_${s.key}`.toLowerCase();
      out.push({
        id,
        kind: 'people',
        label: `${s.label}, ${p.name}`,
        location: { lat: p.lat, lon: p.lon, admin1: p.admin1, country_iso3: p.iso3, city: p.name, place_id: p.id },
        population_represented: pop,
        demographics: { ...s.demographics, income_band: s.demographics.income_band === 'middle' ? (high ? 'upper-middle' : 'lower-middle') : s.demographics.income_band },
        traits: traitsFor(id, s.bias, high),
        context: { country_profile_ref: p.iso3, relevant_companies: [], local_conditions: [p.capital ? 'national capital' : 'regional center', high ? 'high-income economy (mock proxy)' : 'low/middle-income economy (mock proxy)'] },
        voice: s.voice,
      });
    });
  }
  return out;
}

interface InstitutionDef { id: string; label: string; city: string; iso3: string; lat: number; lon: number; headcount: number; types: EventType[] | 'all'; voice: string; companies?: string[] }
// Headcounts are approximate public figures; flagged as mock assumptions in the UI.
export const INSTITUTIONS: InstitutionDef[] = [
  { id: 'inst_who', label: 'World Health Organization', city: 'Geneva', iso3: 'CHE', lat: 46.2, lon: 6.15, headcount: 8000, types: ['outbreak', 'disaster', 'climate'], voice: 'measured, procedural, cites case counts' },
  { id: 'inst_cdc', label: 'US CDC', city: 'Atlanta', iso3: 'USA', lat: 33.75, lon: -84.39, headcount: 13000, types: ['outbreak'], voice: 'technical, cautious' },
  { id: 'inst_ecdc', label: 'ECDC', city: 'Stockholm', iso3: 'SWE', lat: 59.33, lon: 18.07, headcount: 300, types: ['outbreak'], voice: 'risk assessments, formal' },
  { id: 'inst_vn_moh', label: 'Vietnam Ministry of Health', city: 'Hanoi', iso3: 'VNM', lat: 21.03, lon: 105.85, headcount: 2000, types: ['outbreak', 'disaster'], voice: 'official, reassuring, directive' },
  { id: 'inst_fed', label: 'US Federal Reserve', city: 'Washington, D.C.', iso3: 'USA', lat: 38.89, lon: -77.04, headcount: 3000, types: ['finance', 'policy', 'conflict'], voice: 'deliberate, data-dependent' },
  { id: 'inst_ecb', label: 'European Central Bank', city: 'Frankfurt', iso3: 'DEU', lat: 50.11, lon: 8.68, headcount: 4000, types: ['finance', 'policy'], voice: 'formal, inflation-focused' },
  { id: 'inst_pboc', label: "People's Bank of China", city: 'Beijing', iso3: 'CHN', lat: 39.9, lon: 116.4, headcount: 2000, types: ['finance', 'policy'], voice: 'terse, stability-focused' },
  { id: 'inst_eu_commission', label: 'European Commission (Trade)', city: 'Brussels', iso3: 'BEL', lat: 50.85, lon: 4.35, headcount: 32000, types: ['policy', 'launch'], voice: 'regulatory, multilateral' },
  { id: 'inst_apple', label: 'Apple (HQ)', city: 'Cupertino', iso3: 'USA', lat: 37.33, lon: -122.03, headcount: 164000, types: ['launch', 'supply_chain', 'policy'], voice: 'polished, confident, product-first', companies: ['Apple'] },
  { id: 'inst_meta', label: 'Meta Reality Labs', city: 'Menlo Park', iso3: 'USA', lat: 37.48, lon: -122.15, headcount: 70000, types: ['launch'], voice: 'competitive, ecosystem talk', companies: ['Meta'] },
  { id: 'inst_samsung', label: 'Samsung Electronics', city: 'Suwon', iso3: 'KOR', lat: 37.26, lon: 127.03, headcount: 270000, types: ['launch', 'supply_chain'], voice: 'engineering-led, fast follower', companies: ['Samsung'] },
  { id: 'inst_tsmc', label: 'TSMC', city: 'Hsinchu', iso3: 'TWN', lat: 24.8, lon: 120.97, headcount: 77000, types: ['launch', 'supply_chain', 'conflict'], voice: 'capacity and yields', companies: ['TSMC'] },
  { id: 'inst_foxconn', label: 'Foxconn Zhengzhou', city: 'Zhengzhou', iso3: 'CHN', lat: 34.75, lon: 113.63, headcount: 200000, types: ['launch', 'supply_chain', 'outbreak'], voice: 'line supervisor: shifts, quotas, overtime', companies: ['Foxconn'] },
  { id: 'inst_byd', label: 'BYD', city: 'Shenzhen', iso3: 'CHN', lat: 22.54, lon: 114.06, headcount: 900000, types: ['policy', 'launch'], voice: 'volume and price', companies: ['BYD'] },
  { id: 'inst_vw', label: 'Volkswagen Group', city: 'Wolfsburg', iso3: 'DEU', lat: 52.42, lon: 10.79, headcount: 680000, types: ['policy', 'supply_chain'], voice: 'cautious, lobbying-aware', companies: ['Volkswagen'] },
  { id: 'inst_maersk', label: 'Maersk', city: 'Copenhagen', iso3: 'DNK', lat: 55.68, lon: 12.57, headcount: 100000, types: ['supply_chain', 'conflict', 'disaster', 'policy'], voice: 'routes, rates, and transit days', companies: ['Maersk'] },
  { id: 'inst_psa', label: 'Port of Singapore', city: 'Singapore', iso3: 'SGP', lat: 1.26, lon: 103.84, headcount: 20000, types: ['supply_chain', 'outbreak'], voice: 'throughput and dwell times' },
  { id: 'inst_lufthansa', label: 'Lufthansa Group', city: 'Frankfurt', iso3: 'DEU', lat: 50.05, lon: 8.57, headcount: 100000, types: ['outbreak', 'disaster', 'conflict'], voice: 'load factors and route suspensions' },
  { id: 'inst_reuters', label: 'Reuters newsroom', city: 'London', iso3: 'GBR', lat: 51.51, lon: -0.1, headcount: 2500, types: 'all', voice: 'headline register, attribution' },
  { id: 'inst_afad', label: 'AFAD (Türkiye disaster agency)', city: 'Ankara', iso3: 'TUR', lat: 39.93, lon: 32.86, headcount: 7000, types: ['disaster'], voice: 'operational, counts teams and tents' },
  { id: 'inst_unhcr', label: 'UNHCR', city: 'Geneva', iso3: 'CHE', lat: 46.22, lon: 6.14, headcount: 18000, types: ['conflict', 'disaster', 'climate'], voice: 'humanitarian, numbers of displaced' },
  { id: 'inst_bestbuy', label: 'Best Buy store manager', city: 'Columbus', iso3: 'USA', lat: 39.96, lon: -83.0, headcount: 90000, types: ['launch'], voice: 'floor-level: foot traffic, preorders, stock', companies: ['Best Buy'] },
  { id: 'inst_imf', label: 'IMF', city: 'Washington, D.C.', iso3: 'USA', lat: 38.9, lon: -77.04, headcount: 2700, types: ['finance', 'policy', 'conflict'], voice: 'growth revisions, programs' },
  { id: 'inst_opec', label: 'OPEC Secretariat', city: 'Vienna', iso3: 'AUT', lat: 48.21, lon: 16.37, headcount: 150, types: ['conflict', 'policy', 'climate'], voice: 'barrels and quotas' },
];

export function institutionPersonas(eventType: EventType): Persona[] {
  return INSTITUTIONS.filter((d) => d.types === 'all' || d.types.includes(eventType)).map((d) => ({
    id: d.id,
    kind: 'institution',
    label: d.label,
    location: { lat: d.lat, lon: d.lon, admin1: '', country_iso3: d.iso3, city: d.city },
    population_represented: d.headcount,
    demographics: { age_band: 'n/a', income_band: 'n/a', occupation_class: 'institution', education: 'n/a', urban_rural: 'urban' },
    traits: { risk_tolerance: 0.3, institutional_trust: 0.8, media_exposure: 0.9, price_sensitivity: 0.3, tech_adoption: 0.6, social_connectedness: 0.9 },
    context: { country_profile_ref: d.iso3, relevant_companies: d.companies ?? [], local_conditions: ['headcount is an approximate public figure (mock)'] },
    voice: d.voice,
  }));
}
