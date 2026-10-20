// Worldsim contracts. Single source of truth; the Python service mirrors these as Pydantic models (M1+).

export type Theme = 'light' | 'dark';
export type Confidence = 'high' | 'medium' | 'low';
export type Origin = 'data' | 'model' | 'llm' | 'user' | 'mock';

export type PersonaStatus =
  | 'unaware'
  | 'aware'
  | 'reacting'
  | 'affected'
  | 'recovered'
  | 'adopted'
  | 'opposed';

/** Status → code used in the client's Uint8Array frames, and → 0..1 intensity used for shading. */
export const STATUS_CODES: readonly PersonaStatus[] = [
  'unaware',
  'aware',
  'reacting',
  'affected',
  'recovered',
  'adopted',
  'opposed',
];
export const STATUS_INTENSITY: Record<PersonaStatus, number> = {
  unaware: 0,
  aware: 0.3,
  reacting: 0.6,
  affected: 1,
  recovered: 0.45,
  adopted: 1,
  opposed: 0.5,
};

export type EventType =
  | 'outbreak'
  | 'disaster'
  | 'conflict'
  | 'policy'
  | 'finance'
  | 'supply_chain'
  | 'launch'
  | 'corporate'
  | 'election'
  | 'climate'
  | 'social'
  | 'generic';

export type Domain =
  | 'health'
  | 'economy'
  | 'supply_chain'
  | 'politics'
  | 'climate'
  | 'tech_adoption'
  | 'information'
  | 'security';

export interface Provenance {
  source: string;
  as_of: string;
  confidence: Confidence;
  license: string;
}

export interface Assumption {
  id: string;
  text: string;
  value?: number | string | null;
  unit?: string | null;
  origin: Origin;
  confidence: Confidence;
  source?: string | null;
  /** numeric assumptions the user may edit; low/high bound the ensemble draws */
  editable?: boolean;
  low?: number | null;
  high?: number | null;
}

export interface Intervention {
  kind: 'border_closure' | 'lockdown' | 'vaccine' | 'price_change' | 'tariff_change' | 'aid' | 'custom';
  day: number;
  value?: number | null;
  countries: string[];
  text: string;
}

export interface Place {
  /** Natural Earth ne_id, stable and unique */
  id: number;
  name: string;
  country: string;
  iso3: string;
  iso2: string;
  admin1: string;
  lat: number;
  lon: number;
  pop: number;
  capital: boolean;
  hub: boolean;
}

export interface ScenarioSpec {
  title: string;
  prompt: string;
  event_type: EventType;
  domains: Domain[];
  origin: Place | null;
  /** true when the event starts everywhere at once (e.g. a global product launch) */
  global: boolean;
  start_date: string; // ISO date, t0
  horizon_days: number;
  step_days: number;
  actors: string[];
  mechanisms: string[];
  assumptions: Assumption[];
  interventions?: Intervention[];
  clarifying_question?: string | null;
  engine: 'mock-m0' | 'worldsim';
  /** domain module that ran: launch | epidemiology | disaster | trade | generic (mock in M0) */
  module?: string;
  parser?: 'rules' | 'llm';
  confidence: Confidence;
}

export interface Persona {
  id: string;
  kind: 'people' | 'institution';
  label: string;
  location: { lat: number; lon: number; admin1: string; country_iso3: string; city: string; place_id?: number };
  population_represented: number;
  demographics: {
    age_band: string;
    income_band: string;
    occupation_class: string;
    education: string;
    urban_rural: string;
  };
  traits: {
    risk_tolerance: number;
    institutional_trust: number;
    media_exposure: number;
    price_sensitivity: number;
    tech_adoption: number;
    social_connectedness: number;
  };
  context: { country_profile_ref: string; relevant_companies: string[]; local_conditions: string[] };
  voice: string;
  segment?: string;
}

export interface Delta {
  id: string;
  status: PersonaStatus;
  metric?: number;
}

export interface Bubble {
  id: string;
  persona_id: string;
  t: number;
  text: string;
  sentiment: -1 | 0 | 1;
  priority: number;
  why: { event: string; metric: string; before: number; after: number; unit: string; source?: string | null };
  decision?: string | null;
  emotion?: string | null;
  generator?: 'template' | 'llm';
}

export interface SimEvent {
  id: string;
  t: number;
  date: string;
  title: string;
  cause: string;
  places: string[];
  severity: 1 | 2 | 3;
}

export interface Flow {
  from: [number, number];
  to: [number, number];
  weight: number;
  kind: 'spread' | 'trade' | 'movement' | 'adoption';
}

export interface Frame {
  t: number;
  date: string;
  deltas: Delta[];
  bubbles: Bubble[];
  events: SimEvent[];
  flows: Flow[];
  metrics: Record<string, number>;
  /** per-country values of the choropleth layers at this step, e.g. { cases_per_100k: { VNM: 12.3 } } */
  layers?: Record<string, Record<string, number>>;
  /** ensemble band of the key metric at this step: [p5, p25, p50, p75, p95] */
  band?: number[] | null;
}

export interface RunConfig {
  run_id: string;
  seed: number;
  spec: ScenarioSpec;
  created_at: string;
  data_snapshot: string;
  parent_run_id?: string | null;
  branch_at?: number | null;
  /** sim service only (the M0 mock omits them) */
  engine_version?: string;
  ensemble_size?: number;
  label?: string | null;
}

export interface SummaryMetric {
  name: string;
  value: number;
  unit: string;
  low?: number | null;
  high?: number | null;
  low50?: number | null;
  high50?: number | null;
  confidence: Confidence;
  source?: string | null;
}

export interface Summary {
  headline: string;
  metrics: SummaryMetric[];
  note: string;
}

export type ServerEvent =
  | { type: 'personas'; personas: Persona[] }
  | { type: 'frame'; frame: Frame }
  | { type: 'progress'; t: number; total: number; label: string }
  | { type: 'meta'; meta: RunMeta }
  | { type: 'summary'; summary: Summary }
  | { type: 'report'; report: Report }
  | { type: 'done' }
  | { type: 'error'; message: string };

/** One dataset in the store (GET /api/data/catalog). as_of/retrieved are null only when the source is unavailable. */
export interface DataCatalogEntry extends Omit<Provenance, 'as_of'> {
  id: string;
  name: string;
  url: string;
  as_of: string | null;
  retrieved: string | null;
  fields: string[];
  used_for: string;
  note: string | null;
  /** live: fetched now · cached: last good copy after a failed fetch · partial: some records missing · external: maintained outside the pipeline */
  fetch_status: 'live' | 'cached' | 'partial' | 'unavailable' | 'external';
  max_age_days: number;
  rows: number;
  error: string | null;
  snapshot_id: string;
  freshness: 'fresh' | 'stale' | 'unavailable';
  stale: boolean;
  stale_reason: string | null;
}

export type ChatAction =
  | { type: 'zoom'; center: [number, number]; zoom: number }
  | { type: 'layers'; layers: { dots: boolean; institutions: boolean; flows: boolean; bubbles: boolean } }
  | { type: 'branch'; run_id: string; spec: ScenarioSpec; parent_run_id: string }
  | { type: 'compare'; a: string; b: string };

export interface LayerMeta { key: string; label: string; unit: string }

/** Module description sent before the first frame. */
export interface RunMeta {
  run_id: string;
  module: string;
  key_metric: string;
  key_unit: string;
  persona_metric: { name: string; unit: string };
  layers: LayerMeta[];
  ensemble_size: number;
  parent_run_id?: string | null;
  label?: string | null;
  engine: string;
}

export interface RunListItem {
  run_id: string;
  title: string;
  created_at: string;
  parent_run_id: string | null;
  label: string | null;
  module: string;
  seed: number;
}

export interface CausalGraph { nodes: { id: string; label: string }[]; edges: { from: string; to: string; label?: string }[] }

/** Full report, spec section 8. */
export interface Report {
  run_id: string;
  title: string;
  prompt: string;
  event_type: EventType;
  module: string;
  generated_at: string;
  start_date: string;
  end_date: string;
  disclaimer: string;
  headline: string;
  headline_generator: 'template' | 'llm';
  key_outcomes: SummaryMetric[];
  timeline: { date: string; day: number; title: string; cause: string; places: string[] }[];
  geography: {
    tables: Record<string, Record<string, string | number | null>[]>;
    top_by_layer: { iso3: string; country: string; value: number }[];
    layer: LayerMeta | null;
    final_layers: Record<string, Record<string, number>>;
  };
  winners_losers: { winners: { name: string; why: string; detail?: string | null }[]; losers: { name: string; why: string; detail?: string | null }[] };
  voices: { quote: string; persona: string; kind: string; date: string; data: string; generator: string }[];
  causal: CausalGraph;
  sensitivities: { key: string; text: string; unit: string; low: number; high: number; central: number; outcome_low: number; outcome_high: number; outcome_central: number; swing: number; origin: string; source?: string | null }[];
  decision_points: { action: string; trigger: string; effect: string; basis: string }[];
  confidence: { overall: Confidence; reasons: string[]; data_gaps: string[]; stale_sources: string[]; calibration: string; analogs?: { name: string; outcomes: string; source: string }[]; llm_usage: Record<string, number> };
  appendix: { datasets: { id: string; name: string; source: string; as_of: string | null; license: string; confidence: string }[]; assumptions: Assumption[]; run: Record<string, unknown> };
  series: { key: string; unit: string; dates: string[]; band: (number[] | null)[] };
}

export interface CompareResult {
  a: { run_id: string; title: string; label: string | null; interventions: Intervention[] };
  b: { run_id: string; title: string; label: string | null; interventions: Intervention[] };
  metrics: { name: string; unit: string; a: number; a_low: number | null; a_high: number | null; b: number; b_low: number | null; b_high: number | null; delta: number; delta_pct: number | null }[];
  series: { unit: string; dates: string[]; a: (number[] | null)[]; b: (number[] | null)[] };
  layer: { key: string | null; label: string; deltas: { iso3: string; country: string; delta: number }[] };
}
