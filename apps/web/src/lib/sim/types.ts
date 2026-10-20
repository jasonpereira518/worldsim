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
  value?: number | string;
  origin: Origin;
  confidence: Confidence;
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
  clarifying_question?: string;
  engine: 'mock-m0' | 'worldsim';
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
  why: { event: string; metric: string; before: number; after: number; unit: string };
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
}

export interface RunConfig {
  run_id: string;
  seed: number;
  spec: ScenarioSpec;
  created_at: string;
  data_snapshot: string;
  parent_run_id?: string;
  branch_at?: number;
}

export interface SummaryMetric {
  name: string;
  value: number;
  unit: string;
  low?: number;
  high?: number;
  confidence: Confidence;
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
  | { type: 'summary'; summary: Summary }
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

export interface ChatAction {
  type: 'zoom';
  center: [number, number];
  zoom: number;
}
