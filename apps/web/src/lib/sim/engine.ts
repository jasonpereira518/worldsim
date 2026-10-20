// Milestone 0 mock engine. Deterministic hub- and distance-weighted diffusion over Natural Earth places,
// persona status transitions from traits, templated bubbles tied to the metric change that caused them.
// Every number here is labeled origin 'mock'. Real domain modules replace this from Milestone 2.
import type { Bubble, Delta, EventType, Flow, Frame, Persona, PersonaStatus, ScenarioSpec, SimEvent, Summary } from './types';
import { clamp01, mulberry32, unit } from './prng';
import { PLACES } from './parse';
import { institutionPersonas, peoplePersonas } from './personas';

interface Params { rate: number; L: number; reachKm: number; recoverAfter: number; hubBoost: number; selfRate: number; metric: { name: string; unit: string; scale: number } }
const P: Record<EventType, Params> = {
  outbreak:     { rate: 0.3,  L: 1200, reachKm: Infinity, recoverAfter: 14, hubBoost: 1.0, selfRate: 0.6, metric: { name: 'cases', unit: 'cases per 100k', scale: 1800 } },
  disaster:     { rate: 0.9,  L: 250,  reachKm: 600,      recoverAfter: 20, hubBoost: 0.1, selfRate: 0.2, metric: { name: 'displaced', unit: 'displaced per 100k', scale: 4000 } },
  conflict:     { rate: 0.25, L: 600,  reachKm: 3500,     recoverAfter: Infinity, hubBoost: 0.4, selfRate: 0.3, metric: { name: 'displaced', unit: 'displaced per 100k', scale: 2500 } },
  policy:       { rate: 0.35, L: 2500, reachKm: Infinity, recoverAfter: Infinity, hubBoost: 0.8, selfRate: 0.2, metric: { name: 'price_change', unit: '% price change', scale: 12 } },
  finance:      { rate: 0.7,  L: 3000, reachKm: Infinity, recoverAfter: 25, hubBoost: 1.5, selfRate: 0.6, metric: { name: 'drawdown', unit: '% drawdown', scale: 18 } },
  supply_chain: { rate: 0.4,  L: 2000, reachKm: Infinity, recoverAfter: 30, hubBoost: 1.2, selfRate: 0.3, metric: { name: 'lead_time', unit: '% longer lead times', scale: 35 } },
  launch:       { rate: 0.28, L: 2500, reachKm: Infinity, recoverAfter: Infinity, hubBoost: 1.0, selfRate: 0.3, metric: { name: 'adoption', unit: '% adopted', scale: 9 } },
  corporate:    { rate: 0.5,  L: 2000, reachKm: Infinity, recoverAfter: 30, hubBoost: 1.0, selfRate: 0.4, metric: { name: 'attention', unit: 'attention index', scale: 100 } },
  election:     { rate: 0.6,  L: 800,  reachKm: 4000,     recoverAfter: 30, hubBoost: 0.5, selfRate: 0.4, metric: { name: 'attention', unit: 'attention index', scale: 100 } },
  climate:      { rate: 0.2,  L: 1500, reachKm: Infinity, recoverAfter: Infinity, hubBoost: 0.3, selfRate: 0.3, metric: { name: 'impact', unit: 'impact index', scale: 100 } },
  social:       { rate: 0.6,  L: 3000, reachKm: Infinity, recoverAfter: 12, hubBoost: 1.5, selfRate: 0.5, metric: { name: 'attention', unit: 'attention index', scale: 100 } },
  generic:      { rate: 0.3,  L: 1500, reachKm: Infinity, recoverAfter: 30, hubBoost: 0.8, selfRate: 0.3, metric: { name: 'impact', unit: 'impact index', scale: 100 } },
};

const toRad = Math.PI / 180;
export function haversineKm(lat1: number, lon1: number, lat2: number, lon2: number): number {
  const dLat = (lat2 - lat1) * toRad, dLon = (lon2 - lon1) * toRad;
  const a = Math.sin(dLat / 2) ** 2 + Math.cos(lat1 * toRad) * Math.cos(lat2 * toRad) * Math.sin(dLon / 2) ** 2;
  return 2 * 6371 * Math.asin(Math.sqrt(a));
}

// Static geography graph: 8 nearest neighbors (ground contact) + 40 hubs (air travel analog). Built once per process.
const K = 8, HUBS = 40;
let GRAPH: { nbr: Int32Array[]; nbrD: Float32Array[]; hubs: number[]; hubD: Float32Array[] } | null = null;
function graph() {
  if (GRAPH) return GRAPH;
  const n = PLACES.length;
  const hubs = PLACES.map((_, i) => i).filter((i) => PLACES[i].hub || i < 25).slice(0, HUBS);
  const nbr: Int32Array[] = [], nbrD: Float32Array[] = [], hubD: Float32Array[] = [];
  const d = new Float64Array(n);
  for (let i = 0; i < n; i++) {
    const a = PLACES[i];
    for (let j = 0; j < n; j++) d[j] = i === j ? Infinity : haversineKm(a.lat, a.lon, PLACES[j].lat, PLACES[j].lon);
    const idx = Array.from(d.keys()).sort((x, y) => d[x] - d[y]).slice(0, K);
    nbr.push(Int32Array.from(idx)); nbrD.push(Float32Array.from(idx.map((j) => d[j])));
    hubD.push(Float32Array.from(hubs.map((h) => (h === i ? Infinity : d[h]))));
  }
  return (GRAPH = { nbr, nbrD, hubs, hubD });
}

export const addDays = (iso: string, days: number) => { const d = new Date(iso + 'T00:00:00Z'); d.setUTCDate(d.getUTCDate() + days); return d.toISOString().slice(0, 10); };
const fmt = (x: number) => (x >= 1e9 ? (x / 1e9).toFixed(1) + 'B' : x >= 1e6 ? (x / 1e6).toFixed(1) + 'M' : x >= 1e3 ? Math.round(x / 1e3) + 'k' : String(Math.round(x)));
const clamp = (x: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, x));

function nextStatus(cur: PersonaStatus, e: number, p: Persona, type: EventType, sinceAffected: number, recoverAfter: number): PersonaStatus {
  const tr = p.traits;
  if (p.kind === 'institution') {
    if (cur === 'unaware') return e >= 0.05 ? 'aware' : cur;
    if (cur === 'aware') return e >= 0.2 ? 'reacting' : cur;
    if (cur === 'reacting') return e >= 0.5 ? 'affected' : cur;
    return cur;
  }
  switch (cur) {
    case 'unaware': return e >= 0.06 * (1.5 - tr.media_exposure) ? 'aware' : cur;
    case 'aware': return e >= clamp(0.25 + 0.3 * tr.risk_tolerance - 0.15 * tr.social_connectedness, 0.12, 0.6) ? 'reacting' : cur;
    case 'reacting': {
      if (type === 'launch') {
        if (e >= clamp(0.4 + 0.45 * tr.price_sensitivity - 0.3 * tr.tech_adoption, 0.2, 0.95)) return 'adopted';
        return e >= 0.85 && tr.price_sensitivity > 0.6 ? 'opposed' : cur;
      }
      const thr = 0.5 + 0.55 * unit(p.id, 'aff'); // > 1 for ~9%: never affected
      if (e < thr) return cur;
      if ((type === 'policy' || type === 'election' || type === 'social') && tr.institutional_trust < 0.35 && unit(p.id, 'opp') < 0.5) return 'opposed';
      return 'affected';
    }
    case 'affected': return sinceAffected >= recoverAfter ? 'recovered' : cur;
    default: return cur;
  }
}

function metricFor(type: EventType, e: number, p: Persona): number {
  const s = P[type].metric.scale;
  const f = type === 'launch' ? p.traits.tech_adoption * (1.3 - p.traits.price_sensitivity) : type === 'policy' ? 0.5 + p.traits.price_sensitivity : 0.7 + 0.6 * unit(p.id, 'm');
  return +(s * e * f).toFixed(type === 'launch' || type === 'policy' || type === 'finance' ? 1 : 0);
}

type Ctx = { city: string; country: string; m: string; unit: string };
const T = (arr: string[], p: Persona, c: Ctx) => {
  const s = arr[Math.floor(unit(p.id, 'tpl') * arr.length)];
  return s.replace('{city}', c.city).replace('{country}', c.country).replace('{m}', c.m).replace('{unit}', c.unit);
};
const PEOPLE: Partial<Record<EventType, Partial<Record<PersonaStatus, string[]>>>> = {
  outbreak: {
    aware: ['Group chat says there are cases in {city}. Probably nothing.', 'Saw the {city} news. Washing hands more, that is all.'],
    reacting: ['{m} {unit} here now. I am keeping the kids home this week.', 'Masks are sold out in {city}. I ordered online, overpriced.'],
    affected: ['Half my team in {city} is out sick. Deadlines are gone.', 'Schools are closed again. I cannot work and cannot afford a sitter.', 'Clinic in {city} turned us away. Full. {m} {unit}.'],
    recovered: ['Back at work in {city}. Still not sure I trust the numbers.', 'Cases are falling here. First normal week in a month.'],
  },
  launch: {
    aware: ['A $499 headset? I will believe it when I see it in {city}.', 'Everyone in {city} is posting the launch video. Cute.'],
    reacting: ['Preordered. If it ships late to {country} I am cancelling.', 'Tried it at the {city} store. Tempting, but rent comes first.'],
    adopted: ['Got mine. {m}{unit} of people I know have one already in {city}.', 'Third week with it. My laptop is gathering dust.'],
    opposed: ['$499 is a month of rent in {city}. Hard pass.', 'Nice demo, wrong price for {country}. Waiting for the clone.'],
  },
  policy: {
    aware: ['Heard the tariff news on the radio in {city}. Prices will move.', 'Everyone in {city} is asking what this means for car prices.'],
    reacting: ['Dealer in {city} quoted {m}% more than last month. Waiting.', 'I was about to buy an EV. Now I am shopping used.'],
    affected: ['Prices up {m}% in {city}. I kept the old car.', 'My shop imports parts. {m}% higher costs, no room to pass it on.'],
    opposed: ['This hurts {city} workers, not the people it targets. We are protesting.', 'Nobody asked us in {country}. Rally on Saturday.'],
  },
  disaster: {
    aware: ['Felt it in {city}. Everyone is outside checking on neighbors.', 'Power flickered in {city}. Phones are jammed.'],
    reacting: ['No water in our block of {city} since last night.', 'Sleeping in the car tonight. Not going back inside yet.'],
    affected: ['{m} {unit} in {city}. We are in a school gym with 400 others.', 'Our building in {city} is cracked. We are not allowed back.'],
    recovered: ['Moved into a container home outside {city}. It is something.', 'Shop reopened in {city}. Half the street is still rubble.'],
  },
  conflict: {
    aware: ['Watching the news from {city}. Fuel prices jumped already.', 'My cousin near the border in {country} stopped answering.'],
    reacting: ['Stocking rice and fuel in {city}. Everyone is.', 'Flights out of {city} doubled in price overnight.'],
    affected: ['We left {city} with two bags. {m} {unit} on the road with us.', 'Bread is twice the price in {city} and the ATM is empty.'],
  },
  finance: {
    aware: ['Markets are red in {city}. Checked my pension twice today.', 'Bank app in {city} was down for an hour. Coincidence?'],
    reacting: ['Moved savings to cash. {m}% {unit} is enough for me.', 'Boss in {city} froze hiring this morning.'],
    affected: ['Loan rate reset. {m}% {unit} and my payment is up a third.', 'Three shops on my street in {city} closed this month.'],
    recovered: ['Markets stabilised. I am not putting the cash back yet.', 'Hiring in {city} is back, slowly.'],
  },
};
const GENERIC: Partial<Record<PersonaStatus, string[]>> = {
  aware: ['News from {city}: people are talking about it everywhere.', 'Heard about it in {city}. Watching for now.'],
  reacting: ['It is starting to change plans here in {city}. {m} {unit}.', 'People in {city} are adjusting. Prices, schedules, everything.'],
  affected: ['{city} is in the thick of it now: {m} {unit}.', 'Daily life in {city} looks different this week.'],
  recovered: ['Things in {city} are settling. We adapted.'],
  adopted: ['{city} has taken it up: {m} {unit}.'],
  opposed: ['Not for us in {city}. People here are pushing back.'],
};
const INST: Record<PersonaStatus, string[]> = {
  unaware: [],
  aware: ['Monitoring reports from {city}. No action yet.', 'We have seen the {country} signal and convened a call.'],
  reacting: ['Activating our response plan for {country} today.', 'Guidance issued for {country}. Expect updates daily.'],
  affected: ['Operating at surge capacity. {m} {unit} in {country}.', 'All resources committed to the {country} response.'],
  recovered: ['Standing down the emergency posture for {country}.'],
  adopted: ['Scaling production: {country} demand is above plan.'],
  opposed: ['Formally objecting to the measure affecting {country}.'],
};

export interface RunResult { personas: Persona[]; frames: () => Generator<Frame, void, void>; summary: (frames: Frame[]) => Summary }

export function createRun(spec: ScenarioSpec, seed: number): RunResult {
  const type = spec.event_type;
  const prm = P[type];
  const rateAssumption = spec.assumptions.find((a) => a.id === 'rate');
  const scale = type === 'policy' && typeof rateAssumption?.value === 'number' ? rateAssumption.value * 0.4 : prm.metric.scale;
  const params = { ...prm, metric: { ...prm.metric, scale } };
  const g = graph();
  const n = PLACES.length;
  const rng = mulberry32(seed);
  const steps = Math.ceil(spec.horizon_days / spec.step_days);

  const people = peoplePersonas(PLACES);
  const institutions = institutionPersonas(type);
  const personas = [...people, ...institutions];
  const cityIdx = new Map(PLACES.map((p, i) => [p.id, i]));
  const personaCity = people.map((p) => cityIdx.get(p.location.place_id!)!);
  const countryCities = new Map<string, number[]>();
  PLACES.forEach((p, i) => countryCities.set(p.iso3, [...(countryCities.get(p.iso3) ?? []), i]));

  // Origin + reach cap
  let originIdx = -1;
  if (spec.origin) {
    originIdx = cityIdx.get(spec.origin.id) ?? -1;
    if (originIdx < 0) { let best = Infinity; PLACES.forEach((p, i) => { const d = haversineKm(p.lat, p.lon, spec.origin!.lat, spec.origin!.lon); if (d < best) { best = d; originIdx = i; } }); }
  }
  const cap = new Float64Array(n).fill(1);
  if (originIdx >= 0 && params.reachKm !== Infinity) {
    const o = PLACES[originIdx];
    PLACES.forEach((p, i) => { cap[i] = Math.exp(-((haversineKm(o.lat, o.lon, p.lat, p.lon) / params.reachKm) ** 2)); });
  }
  // Edge weights for this event type
  const W: { j: number; w: number }[][] = [];
  for (let i = 0; i < n; i++) {
    const edges: { j: number; w: number }[] = [];
    for (let k = 0; k < K; k++) edges.push({ j: g.nbr[i][k], w: Math.exp(-g.nbrD[i][k] / params.L) });
    g.hubs.forEach((h, k) => { if (h !== i) edges.push({ j: h, w: params.hubBoost * 0.08 * Math.sqrt(PLACES[h].pop / 35e6) * Math.exp(-g.hubD[i][k] / 10000) }); });
    const total = edges.reduce((s, e) => s + e.w, 0);
    W.push(total > 1.2 ? edges.map((e) => ({ j: e.j, w: (e.w * 1.2) / total })) : edges);
  }

  function* frames(): Generator<Frame, void, void> {
    const e = new Float64Array(n);
    if (spec.global) g.hubs.forEach((h) => { e[h] = Math.max(e[h], 0.3 * cap[h]); });
    if (originIdx >= 0) e[originIdx] = cap[originIdx];
    const status: PersonaStatus[] = personas.map(() => 'unaware');
    const metric = new Float64Array(personas.length);
    const since = new Int32Array(personas.length);
    const reached = new Set<string>();
    const milestones = new Set<string>();
    const totalPop = people.reduce((s, p) => s + p.population_represented, 0);
    const inflow = new Float64Array(n);
    const bestSrc = new Int32Array(n);

    for (let t = 0; t <= steps; t++) {
      const date = addDays(spec.start_date, t * spec.step_days);
      const flows: Flow[] = [];
      if (t > 0) {
        for (let i = 0; i < n; i++) {
          let s = 0, bi = -1, bw = 0;
          for (const { j, w } of W[i]) { const c = w * e[j]; s += c; if (c > bw) { bw = c; bi = j; } }
          inflow[i] = s; bestSrc[i] = bi;
        }
        for (let i = 0; i < n; i++) {
          const before = e[i];
          const noise = 0.9 + 0.2 * rng();
          e[i] = Math.min(cap[i], before + params.rate * noise * (cap[i] - before) * (inflow[i] + params.selfRate * before));
          if (before < 0.05 && e[i] >= 0.05 && bestSrc[i] >= 0 && flows.length < 40) {
            const s = PLACES[bestSrc[i]], d = PLACES[i];
            flows.push({ from: [s.lon, s.lat], to: [d.lon, d.lat], weight: clamp01(inflow[i]), kind: type === 'launch' ? 'adoption' : type === 'conflict' || type === 'disaster' ? 'movement' : 'spread' });
          }
        }
      }
      const deltas: Delta[] = [], bubbles: Bubble[] = [], events: SimEvent[] = [];
      let globalMean = 0;
      for (let i = 0; i < n; i++) globalMean += e[i] * PLACES[i].pop;
      globalMean /= 1.5e9;

      personas.forEach((p, k) => {
        let ex: number;
        if (p.kind === 'people') ex = e[personaCity[k]];
        else { const cities = countryCities.get(p.location.country_iso3) ?? []; ex = Math.max(globalMean * 2.5, ...cities.map((i) => e[i])); }
        const cur = status[k];
        const nxt = nextStatus(cur, ex, p, type, t - since[k], params.recoverAfter);
        const m = metricFor(type, ex, p);
        if (nxt !== cur) {
          status[k] = nxt;
          if (nxt === 'affected') since[k] = t;
          deltas.push({ id: p.id, status: nxt, metric: m });
          const first = p.kind === 'people' && !reached.has(p.location.country_iso3) && (nxt === 'reacting' || nxt === 'affected') && ex >= 0.3;
          if (first) {
            reached.add(p.location.country_iso3);
            if (reached.size <= 8 || reached.size % 25 === 0) events.push({ id: `e_${t}_${p.location.country_iso3}`, t, date, title: `Reaches ${PLACES[personaCity[k]].country}`, cause: `${p.location.city} exposure ${ex.toFixed(2)} via ${bestSrc[personaCity[k]] >= 0 ? PLACES[bestSrc[personaCity[k]]].name : 'origin'}`, places: [p.location.city], severity: reached.size <= 3 ? 3 : 2 });
          }
          const speak = p.kind === 'institution' || nxt === 'affected' || nxt === 'adopted' || nxt === 'opposed' || nxt === 'recovered' || (nxt === 'reacting' && unit(p.id, `r${t}`) < 0.5) || (nxt === 'aware' && unit(p.id, `a${t}`) < 0.12);
          if (speak) {
            const ctx: Ctx = { city: p.location.city, country: PLACES[personaCity[k] ?? 0]?.country ?? p.location.country_iso3, m: String(m), unit: params.metric.unit };
            if (p.kind === 'institution') ctx.country = p.location.city;
            const table = p.kind === 'institution' ? INST[nxt] : (PEOPLE[type]?.[nxt] ?? GENERIC[nxt] ?? GENERIC.affected!);
            let text = T(table.length ? table : GENERIC.affected!, p, ctx);
            if (text.length > 140) text = text.slice(0, 137) + '…';
            const pri = Math.log10(Math.max(p.population_represented, 10)) * (p.kind === 'institution' ? 1.3 : 1) * (first ? 1.8 : 1) * (nxt === 'affected' || nxt === 'adopted' ? 1.2 : nxt === 'aware' ? 0.6 : 1);
            const sentiment: Bubble['sentiment'] = nxt === 'adopted' || nxt === 'recovered' ? 1 : nxt === 'aware' ? 0 : -1;
            bubbles.push({ id: `b_${t}_${p.id}`, persona_id: p.id, t, text, sentiment, priority: +pri.toFixed(2), why: { event: `${cur} → ${nxt}: local exposure ${ex.toFixed(2)}`, metric: params.metric.name, before: metric[k], after: m, unit: params.metric.unit } });
          }
        }
        metric[k] = m;
      });

      let awarePop = 0, affectedPop = 0, everPop = 0, mSum = 0;
      people.forEach((p, k) => {
        const s = status[k], pop = p.population_represented;
        if (s !== 'unaware') awarePop += pop;
        if (s === 'affected' || s === 'adopted' || s === 'opposed') affectedPop += pop;
        if (s === 'affected' || s === 'adopted' || s === 'opposed' || s === 'recovered') everPop += pop;
        mSum += metric[k] * pop;
      });
      for (const [share, label] of [[0.1, '10%'], [0.5, '50%']] as const) {
        if (!milestones.has(label) && everPop / totalPop >= share) { milestones.add(label); events.push({ id: `e_${t}_m${label}`, t, date, title: `${label} of represented population ${type === 'launch' ? 'adopting' : 'affected'}`, cause: `${fmt(everPop)} people across ${reached.size} countries and territories`, places: [], severity: 3 }); }
      }
      yield { t, date, deltas, bubbles, events, flows, metrics: { aware_pop: awarePop, affected_pop: affectedPop, ever_affected_pop: everPop, countries_reached: reached.size, mean_exposure: +globalMean.toFixed(4), [params.metric.name]: +(mSum / totalPop).toFixed(2) } };
    }
  }

  const summary = (all: Frame[]): Summary => {
    const last = all[all.length - 1];
    const peak = all.reduce((m, f) => Math.max(m, f.metrics.affected_pop), 0);
    const peakT = all.find((f) => f.metrics.affected_pop === peak)?.t ?? 0;
    const verb = type === 'launch' ? 'adopting' : 'affected';
    const unitName = params.metric.unit;
    return {
      headline: `${spec.title}: by ${last.date}, ${fmt(last.metrics.ever_affected_pop)} of ${fmt(all[0].metrics.ever_affected_pop + people.reduce((s, p) => s + p.population_represented, 0))} represented people were ${verb} across ${last.metrics.countries_reached} countries and territories, peaking on day ${peakT * spec.step_days} (single deterministic mock run, low confidence).`,
      metrics: [
        { name: `Population ${verb} (cumulative)`, value: last.metrics.ever_affected_pop, unit: 'people', confidence: 'low' },
        { name: `Peak concurrently ${verb}`, value: peak, unit: 'people', confidence: 'low' },
        { name: 'Countries and territories reached', value: last.metrics.countries_reached, unit: 'of 217 (Natural Earth admin-0)', confidence: 'low' },
        { name: `Mean ${params.metric.name.replace('_', ' ')} at horizon`, value: last.metrics[params.metric.name], unit: unitName, confidence: 'low' },
        { name: 'Days to 10 countries', value: (all.find((f) => f.metrics.countries_reached >= 10)?.t ?? steps) * spec.step_days, unit: 'days', confidence: 'low' },
      ],
      note: 'Mock engine (Milestone 0): one deterministic diffusion run, no intervals. Ensembles with 50% and 90% bands arrive with the real domain modules in Milestone 3.',
    };
  };

  return { personas, frames, summary };
}
