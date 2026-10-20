// Prompt → ScenarioSpec. Milestone 0: keyword rules + place matching. Milestone 2 replaces this with an
// LLM parser constrained to the same ScenarioSpec schema; everything here is labeled origin 'mock'/'model'.
import type { Assumption, Domain, EventType, Place, ScenarioSpec } from './types';
import placesJson from '../../../data/places.json';

export const T0 = '2026-10-20';
export const PLACES = placesJson as Place[];

interface Rule {
  type: EventType;
  words: RegExp;
  domains: Domain[];
  horizon: number;
  step: number;
  mechanisms: string[];
  actors: string[];
}

// Order matters: first matching rule wins.
const RULES: Rule[] = [
  { type: 'outbreak', words: /\b(outbreak|pandemic|epidemic|virus|variant|h5n1|h1n1|ebola|influenza|flu|transmission|infect\w*|cholera|measles|covid|sars|mers)\b/i,
    domains: ['health', 'economy', 'information'], horizon: 180, step: 1,
    mechanisms: ['human-to-human transmission', 'air-travel seeding', 'health-system capacity', 'behavioral response'],
    actors: ['WHO', 'national health ministries', 'hospitals', 'airlines'] },
  { type: 'disaster', words: /\b(earthquake|quake|magnitude|tsunami|hurricane|cyclone|typhoon|flood\w*|wildfire|eruption|volcano|landslide)\b/i,
    domains: ['security', 'economy', 'supply_chain'], horizon: 60, step: 1,
    mechanisms: ['direct damage', 'displacement', 'infrastructure outage', 'relief and recovery'],
    actors: ['civil protection agency', 'hospitals', 'insurers', 'port and grid operators'] },
  { type: 'policy', words: /\b(tariffs?|sanctions?|bans?|imposes?|regulat\w*|legislat\w*|embargo|quota|subsid\w*)\b/i,
    domains: ['economy', 'supply_chain', 'politics'], horizon: 365, step: 7,
    mechanisms: ['price pass-through', 'trade rerouting', 'retaliation', 'substitution'],
    actors: ['regulators', 'importers', 'manufacturers', 'consumers'] },
  { type: 'conflict', words: /\b(war|invades?|invasion|conflict|missiles?|troops|ceasefire|coup|insurgen\w*|airstrikes?)\b/i,
    domains: ['security', 'politics', 'economy'], horizon: 180, step: 1,
    mechanisms: ['escalation', 'displacement', 'sanctions', 'commodity shock'],
    actors: ['governments', 'UNHCR', 'energy markets', 'neighboring states'] },
  { type: 'finance', words: /\b(defaults?|bank run|crash\w*|bankrupt\w*|rate (hike|cut)|devalu\w*|collapse|credit crunch|recession|stock market)\b/i,
    domains: ['economy', 'information'], horizon: 90, step: 1,
    mechanisms: ['market reaction', 'contagion', 'credit tightening', 'policy response'],
    actors: ['central banks', 'banks', 'investors', 'rating agencies'] },
  { type: 'supply_chain', words: /\b(blockade|canal|strait|shipping|port closure|chip shortage|semiconductor|supply chain)\b/i,
    domains: ['supply_chain', 'economy'], horizon: 120, step: 1,
    mechanisms: ['network disruption', 'inventory buffers', 'rerouting', 'bottlenecks'],
    actors: ['shippers', 'manufacturers', 'ports', 'insurers'] },
  { type: 'launch', words: /\b(launch\w*|releases?|unveils?|headset|iphone|smartphone|rollout|ships a|product)\b/i,
    domains: ['tech_adoption', 'economy', 'supply_chain'], horizon: 365, step: 7,
    mechanisms: ['media awareness', 'Bass diffusion by segment', 'price elasticity', 'supply constraints', 'competitor response'],
    actors: ['the company', 'retailers', 'suppliers', 'competitors'] },
  { type: 'corporate', words: /\b(acqui\w*|merger|m&a|recalls?|layoffs?|ipo|spin-?off)\b/i,
    domains: ['economy', 'information'], horizon: 120, step: 1,
    mechanisms: ['market reaction', 'workforce effects', 'customer response'], actors: ['the company', 'regulators', 'investors'] },
  { type: 'election', words: /\b(elections?|referendum|ballot|wins the presidency)\b/i,
    domains: ['politics', 'economy', 'information'], horizon: 90, step: 1,
    mechanisms: ['opinion dynamics', 'policy expectations', 'market repricing'], actors: ['parties', 'voters', 'media'] },
  { type: 'climate', words: /\b(heat ?wave|drought|monsoon|el ni[ñn]o|sea level|glacier|emissions)\b/i,
    domains: ['climate', 'economy', 'health'], horizon: 180, step: 7,
    mechanisms: ['exposure', 'agricultural yield', 'energy demand', 'adaptation'], actors: ['farmers', 'utilities', 'governments'] },
  { type: 'social', words: /\b(protests?|boycott|viral|trend\w*|strikes?|movement|festival|world cup|olympics)\b/i,
    domains: ['information', 'politics', 'economy'], horizon: 60, step: 1,
    mechanisms: ['social amplification', 'attention cycle', 'institutional response'], actors: ['media', 'platforms', 'authorities'] },
];
const GENERIC: Rule = { type: 'generic', words: /./, domains: ['economy', 'information'], horizon: 120, step: 1,
  mechanisms: ['closest-analog stock-and-flow (generic fallback)'], actors: ['governments', 'media', 'markets'] };

// Mock entity resolver: a handful of companies → nearest Natural Earth place to their HQ. M2 resolves live.
const COMPANIES: Record<string, string> = {
  apple: 'San Francisco', meta: 'San Francisco', google: 'San Francisco', nvidia: 'San Francisco', openai: 'San Francisco',
  tesla: 'Austin', microsoft: 'Seattle', amazon: 'Seattle', boeing: 'Chicago', samsung: 'Seoul', sony: 'Tokyo', toyota: 'Nagoya',
  tsmc: 'Taipei', foxconn: 'Taipei', byd: 'Shenzhen', huawei: 'Shenzhen', airbus: 'Toulouse', maersk: 'Copenhagen',
  volkswagen: 'Berlin', siemens: 'Munich', tata: 'Mumbai',
};
const DEMONYMS: Record<string, string> = {
  chinese: 'China', vietnamese: 'Vietnam', american: 'United States of America', japanese: 'Japan', korean: 'South Korea',
  indian: 'India', russian: 'Russia', german: 'Germany', french: 'France', british: 'United Kingdom', brazilian: 'Brazil',
  mexican: 'Mexico', turkish: 'Turkey', iranian: 'Iran', israeli: 'Israel', saudi: 'Saudi Arabia', taiwanese: 'Taiwan',
  indonesian: 'Indonesia', nigerian: 'Nigeria', egyptian: 'Egypt', canadian: 'Canada', australian: 'Australia', italian: 'Italy',
  spanish: 'Spain', eu: 'Belgium', 'european union': 'Belgium', 'the eu': 'Belgium', uk: 'United Kingdom', us: 'United States of America',
  usa: 'United States of America', 'united states': 'United States of America',
};

const byName = new Map<string, Place>();
const countryBest = new Map<string, Place>();
for (const p of PLACES) {
  const k = p.name.toLowerCase();
  if (!byName.has(k) || byName.get(k)!.pop < p.pop) byName.set(k, p);
  const c = p.country.toLowerCase();
  const cur = countryBest.get(c);
  if (!cur || (p.capital && !cur.capital) || (p.capital === cur.capital && p.pop > cur.pop)) countryBest.set(c, p);
}
const escape = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
const hasWord = (text: string, word: string) => new RegExp(`(^|[^a-z])${escape(word)}([^a-z]|$)`, 'i').test(text);

/** Longest place / country / demonym / company mention in the text, or null. */
export function findPlace(text: string): Place | null {
  const lower = text.toLowerCase();
  let best: Place | null = null;
  let bestLen = 0;
  const consider = (key: string, p: Place | undefined) => {
    if (p && key.length > bestLen && hasWord(lower, key)) { best = p; bestLen = key.length; }
  };
  for (const [k, p] of byName) if (k.length > 3) consider(k, p);
  for (const [k, p] of countryBest) consider(k, p);
  for (const [k, c] of Object.entries(DEMONYMS)) consider(k, countryBest.get(c.toLowerCase()));
  return best;
}

export function findCompany(text: string): { name: string; hq: Place | null } | null {
  const lower = text.toLowerCase();
  for (const [k, city] of Object.entries(COMPANIES)) if (hasWord(lower, k)) return { name: k[0].toUpperCase() + k.slice(1), hq: byName.get(city.toLowerCase()) ?? null };
  return null;
}

const MONTHS = ['jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec'];
export function parseStartDate(text: string, t0 = T0): string {
  const base = new Date(t0 + 'T00:00:00Z');
  const lower = text.toLowerCase();
  const m = lower.match(/\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+(\d{1,2})(?:st|nd|rd|th)?(?:,?\s+(\d{4}))?/);
  if (m) {
    const d = new Date(Date.UTC(m[3] ? +m[3] : base.getUTCFullYear(), MONTHS.indexOf(m[1]), +m[2]));
    if (!m[3] && d < base) d.setUTCFullYear(d.getUTCFullYear() + 1);
    return d.toISOString().slice(0, 10);
  }
  const rel = lower.match(/\bin (\d+) (days?|weeks?|months?)\b/) ?? lower.match(/\bnext (week|month|year)\b/);
  if (rel) {
    const n = rel.length === 3 ? +rel[1] : 1;
    const unitWord = rel.length === 3 ? rel[2] : rel[1];
    if (unitWord.startsWith('day')) base.setUTCDate(base.getUTCDate() + n);
    else if (unitWord.startsWith('week')) base.setUTCDate(base.getUTCDate() + 7 * n);
    else if (unitWord.startsWith('month')) base.setUTCMonth(base.getUTCMonth() + n);
    else base.setUTCFullYear(base.getUTCFullYear() + n);
    return base.toISOString().slice(0, 10);
  }
  if (/\btomorrow\b/.test(lower)) { base.setUTCDate(base.getUTCDate() + 1); return base.toISOString().slice(0, 10); }
  return t0;
}

export function parsePrompt(prompt: string, answers: { origin?: string } = {}): ScenarioSpec {
  const text = prompt.trim();
  const rule = RULES.find((r) => r.words.test(text)) ?? GENERIC;
  const company = findCompany(text);
  const place = findPlace(answers.origin ?? '') ?? findPlace(text);
  const globalByNature = rule.type === 'launch' || rule.type === 'finance' || rule.type === 'climate';
  const origin = place ?? company?.hq ?? null;
  const global = globalByNature || (!place && !!company);

  const assumptions: Assumption[] = [
    { id: 'engine', text: 'Mock engine (Milestone 0): hub- and distance-weighted diffusion, not a calibrated domain model', origin: 'mock', confidence: 'low' },
    { id: 't0', text: `Simulated today is ${T0}`, origin: 'user', confidence: 'high' },
    { id: 'population', text: 'Population weights from Natural Earth pop_max (metro estimates, c. 2015)', origin: 'data', confidence: 'medium' },
    { id: 'horizon', text: `Horizon ${rule.horizon} days in steps of ${rule.step} day(s)`, value: rule.horizon, origin: 'model', confidence: 'medium' },
  ];
  const price = text.match(/\$\s?(\d[\d,]*(?:\.\d+)?)/);
  if (price) assumptions.push({ id: 'price', text: `Price point $${price[1]}`, value: +price[1].replace(/,/g, ''), origin: 'user', confidence: 'high' });
  const pct = text.match(/(\d+(?:\.\d+)?)\s?%/);
  if (pct) assumptions.push({ id: 'rate', text: `Rate ${pct[1]}%`, value: +pct[1], origin: 'user', confidence: 'high' });
  const mag = text.match(/magnitude\s?(\d(?:\.\d)?)/i);
  if (mag) assumptions.push({ id: 'magnitude', text: `Magnitude ${mag[1]}`, value: +mag[1], origin: 'user', confidence: 'high' });
  if (!place && origin) assumptions.push({ id: 'origin', text: `Origin set to ${origin.name} (nearest place to ${company?.name} HQ)`, origin: 'mock', confidence: 'low' });

  const needsOrigin = !origin && !global;
  const actors = [...(company ? [company.name] : []), ...(origin ? [origin.country] : []), ...rule.actors];
  const title = text.length > 80 ? text.slice(0, 77).trimEnd() + '…' : text;
  return {
    title: title[0].toUpperCase() + title.slice(1),
    prompt: text,
    event_type: rule.type,
    domains: rule.domains,
    origin,
    global,
    start_date: parseStartDate(text),
    horizon_days: rule.horizon,
    step_days: rule.step,
    actors,
    mechanisms: rule.mechanisms,
    assumptions,
    clarifying_question: needsOrigin ? 'Where does this start? Name a city or country.' : undefined,
    engine: 'mock-m0',
    confidence: rule === GENERIC ? 'low' : 'medium',
  };
}
