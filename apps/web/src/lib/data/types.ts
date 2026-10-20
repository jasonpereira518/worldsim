// Read API contracts for the data layer (Milestone 1). Mirrors data/pipeline/schema.sql; every value carries provenance.
import type { Provenance } from '@/lib/sim/types';

export interface Sourced extends Provenance {
  /** when the pipeline fetched it, ISO-8601 UTC */
  retrieved: string;
}

export interface Missing {
  field: string;
  reason: string;
}

export interface IndicatorValue extends Sourced {
  key: string;
  indicator: string;
  name: string;
  unit: string;
  /** latest observed year */
  year: number;
  value: number;
}

export interface AgeBand {
  band: string;
  female: number;
  male: number;
}

export interface CountrySummary {
  iso3: string;
  iso2: string | null;
  name: string;
  type: string;
  region: string | null;
  income_group: string | null;
  population: number | null;
  population_year: number | null;
  lat: number;
  lon: number;
}

export interface CountryProfile {
  snapshot_id: string;
  iso3: string;
  iso2: string | null;
  name: string;
  name_long: string | null;
  formal_name: string | null;
  type: string;
  sovereign_iso3: string | null;
  continent: string | null;
  subregion: string | null;
  centroid: { lat: number; lon: number };
  label_point: { lat: number; lon: number } | null;
  /** names, boundary, centroid */
  provenance: Sourced;
  /** wb_income, wb_region, wb_lending */
  groups: Record<string, { code: string; label: string } & Sourced>;
  /** latest observed value per indicator key; unobserved keys are listed in `missing` */
  indicators: Record<string, IndicatorValue>;
  /** people per 5-year band: WDI shares × female/male totals, latest year with every band */
  age_structure: ({ year: number; unit: 'people'; bands: AgeBand[] } & Sourced) | null;
  admin1: { id: number; name: string; type: string | null; iso_3166_2: string | null; lat: number; lon: number }[];
  admin1_provenance: Sourced | null;
  /** full annual series per indicator key, only with ?series=1 */
  series?: Record<string, { year: number; value: number }[]>;
  missing: Missing[];
}

export interface CompanySummary {
  id: string;
  name: string;
  ticker: string | null;
  exchange: string | null;
  country_iso3: string | null;
  industry: string | null;
  employees: number | null;
  reference: boolean;
}

export type FinancialMetric = 'revenue' | 'net_income' | 'cash' | 'debt' | 'employees';

export interface FinancialValue extends Sourced {
  value: number | null;
  unit: string | null;
  period_start: string | null;
  period_end: string | null;
  form: string | null;
  concept: string | null;
  missing_reason: string | null;
}

export interface CompanySite extends Sourced {
  kind: 'headquarters' | 'legal_address';
  name: string | null;
  address: string | null;
  city: string | null;
  region: string | null;
  country_iso3: string | null;
  lat: number | null;
  lon: number | null;
}

export interface CompanyProfile {
  snapshot_id: string;
  id: string;
  qid: string;
  name: string;
  description: string | null;
  industry: string | null;
  ticker: string | null;
  exchange: string | null;
  country_iso3: string | null;
  website: string | null;
  lei: string | null;
  cik: string | null;
  employees: number | null;
  employees_as_of: string | null;
  reference: boolean;
  /** identity fields above (Wikidata) */
  provenance: Sourced;
  legal: ({ lei: string; legal_name: string; jurisdiction: string | null; legal_form: string | null; entity_status: string | null; registration_status: string | null } & Sourced) | null;
  sites: CompanySite[];
  financials: Partial<Record<FinancialMetric, FinancialValue>>;
  missing: Missing[];
}
