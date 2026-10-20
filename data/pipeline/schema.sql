-- Worldsim data store, logical schema v1. DuckDB dialect; ports to Postgres/PostGIS by swapping
-- regexp_full_match for `~` and the GeoJSON text columns for geometry(…, 4326).
-- Every row carries provenance: source, as_of, confidence, license, retrieved (UTC).
-- The constraints are the data contract: a snapshot that violates them is never published.

CREATE TABLE catalog (
  id           VARCHAR PRIMARY KEY,
  name         VARCHAR NOT NULL,
  source       VARCHAR NOT NULL,
  url          VARCHAR NOT NULL,
  as_of        DATE,
  retrieved    TIMESTAMP,
  license      VARCHAR NOT NULL,
  confidence   VARCHAR NOT NULL CHECK (confidence IN ('high', 'medium', 'low')),
  fields       VARCHAR[] NOT NULL,
  used_for     VARCHAR NOT NULL,
  note         VARCHAR,
  -- live: every request answered now · cached: some answered from the last good copy · partial: some records
  -- could not be fetched at all (labeled missing) · unavailable: nothing loaded · external: maintained outside this pipeline
  fetch_status VARCHAR NOT NULL CHECK (fetch_status IN ('live', 'cached', 'partial', 'unavailable', 'external')),
  max_age_days INTEGER NOT NULL,
  rows         INTEGER NOT NULL,
  error        VARCHAR,
  CHECK (fetch_status = 'unavailable' OR (as_of IS NOT NULL AND retrieved IS NOT NULL))
);

CREATE TABLE countries (
  iso3           VARCHAR PRIMARY KEY CHECK (regexp_full_match(iso3, '[A-Z]{3}')),
  iso2           VARCHAR CHECK (iso2 IS NULL OR regexp_full_match(iso2, '[A-Z]{2}')),
  name           VARCHAR NOT NULL,
  name_long      VARCHAR,
  formal_name    VARCHAR,
  ne_type        VARCHAR NOT NULL,  -- Sovereign country | Country | Dependency | Disputed | Indeterminate | Lease
  sovereign_iso3 VARCHAR,
  continent      VARCHAR,
  subregion      VARCHAR,
  centroid_lat   DOUBLE NOT NULL CHECK (centroid_lat BETWEEN -90 AND 90),
  centroid_lon   DOUBLE NOT NULL CHECK (centroid_lon BETWEEN -180 AND 180),
  label_lat      DOUBLE,
  label_lon      DOUBLE,
  geometry       VARCHAR NOT NULL,  -- GeoJSON geometry, EPSG:4326
  source VARCHAR NOT NULL, as_of DATE NOT NULL, license VARCHAR NOT NULL, retrieved TIMESTAMP NOT NULL,
  confidence VARCHAR NOT NULL CHECK (confidence IN ('high', 'medium', 'low'))
);

-- Categorical classifications (World Bank income group, region, lending type), one row per scheme.
CREATE TABLE country_groups (
  iso3   VARCHAR NOT NULL CHECK (regexp_full_match(iso3, '[A-Z]{3}')),
  scheme VARCHAR NOT NULL,
  code   VARCHAR NOT NULL,
  label  VARCHAR NOT NULL,
  source VARCHAR NOT NULL, as_of DATE NOT NULL, license VARCHAR NOT NULL, retrieved TIMESTAMP NOT NULL,
  confidence VARCHAR NOT NULL CHECK (confidence IN ('high', 'medium', 'low')),
  PRIMARY KEY (iso3, scheme)
);

-- Long-format time series. Only observed values are stored; an absent (iso3, indicator) is reported as missing.
CREATE TABLE indicators (
  iso3      VARCHAR NOT NULL CHECK (regexp_full_match(iso3, '[A-Z]{3}')),
  indicator VARCHAR NOT NULL,  -- source code, e.g. SP.POP.TOTL
  key       VARCHAR NOT NULL,  -- stable short name used by the API, e.g. population
  name      VARCHAR NOT NULL,
  unit      VARCHAR NOT NULL,
  year      INTEGER NOT NULL CHECK (year BETWEEN 1960 AND 2100),
  value     DOUBLE NOT NULL,
  source VARCHAR NOT NULL, as_of DATE NOT NULL, license VARCHAR NOT NULL, retrieved TIMESTAMP NOT NULL,
  confidence VARCHAR NOT NULL CHECK (confidence IN ('high', 'medium', 'low')),
  PRIMARY KEY (iso3, indicator, year)
);

CREATE TABLE admin1 (
  id         BIGINT PRIMARY KEY,  -- Natural Earth ne_id
  iso3       VARCHAR NOT NULL CHECK (regexp_full_match(iso3, '[A-Z]{3}')),
  name       VARCHAR NOT NULL,
  type       VARCHAR,
  iso_3166_2 VARCHAR,
  lat        DOUBLE NOT NULL CHECK (lat BETWEEN -90 AND 90),
  lon        DOUBLE NOT NULL CHECK (lon BETWEEN -180 AND 180),
  geometry   VARCHAR NOT NULL,
  source VARCHAR NOT NULL, as_of DATE NOT NULL, license VARCHAR NOT NULL, retrieved TIMESTAMP NOT NULL,
  confidence VARCHAR NOT NULL CHECK (confidence IN ('high', 'medium', 'low'))
);

CREATE TABLE companies (
  id              VARCHAR PRIMARY KEY CHECK (regexp_full_match(id, '[a-z0-9-]+')),
  qid             VARCHAR NOT NULL UNIQUE,
  name            VARCHAR NOT NULL,
  description     VARCHAR,
  industry        VARCHAR,
  ticker          VARCHAR,
  exchange        VARCHAR,
  country_iso3    VARCHAR CHECK (country_iso3 IS NULL OR regexp_full_match(country_iso3, '[A-Z]{3}')),
  website         VARCHAR,
  lei             VARCHAR CHECK (lei IS NULL OR regexp_full_match(lei, '[A-Z0-9]{20}')),
  cik             VARCHAR,
  employees       BIGINT CHECK (employees IS NULL OR employees > 0),
  employees_as_of DATE,
  reference       BOOLEAN NOT NULL,  -- part of a reference walkthrough, always included
  source VARCHAR NOT NULL, as_of DATE NOT NULL, license VARCHAR NOT NULL, retrieved TIMESTAMP NOT NULL,
  confidence VARCHAR NOT NULL CHECK (confidence IN ('high', 'medium', 'low'))
);

CREATE TABLE company_legal (
  company_id          VARCHAR PRIMARY KEY,
  lei                 VARCHAR NOT NULL,
  legal_name          VARCHAR NOT NULL,
  jurisdiction        VARCHAR,
  legal_form          VARCHAR,
  entity_status       VARCHAR,
  registration_status VARCHAR,
  source VARCHAR NOT NULL, as_of DATE NOT NULL, license VARCHAR NOT NULL, retrieved TIMESTAMP NOT NULL,
  confidence VARCHAR NOT NULL CHECK (confidence IN ('high', 'medium', 'low'))
);

CREATE TABLE company_sites (
  company_id   VARCHAR NOT NULL,
  kind         VARCHAR NOT NULL CHECK (kind IN ('headquarters', 'legal_address')),
  name         VARCHAR,
  address      VARCHAR,
  city         VARCHAR,
  region       VARCHAR,
  country_iso3 VARCHAR CHECK (country_iso3 IS NULL OR regexp_full_match(country_iso3, '[A-Z]{3}')),
  lat          DOUBLE CHECK (lat IS NULL OR lat BETWEEN -90 AND 90),
  lon          DOUBLE CHECK (lon IS NULL OR lon BETWEEN -180 AND 180),
  source VARCHAR NOT NULL, as_of DATE NOT NULL, license VARCHAR NOT NULL, retrieved TIMESTAMP NOT NULL,
  confidence VARCHAR NOT NULL CHECK (confidence IN ('high', 'medium', 'low')),
  PRIMARY KEY (company_id, kind, source)
);

-- Latest annual value per metric. A metric that could not be filled is a row with value NULL and a reason.
CREATE TABLE company_financials (
  company_id     VARCHAR NOT NULL,
  metric         VARCHAR NOT NULL CHECK (metric IN ('revenue', 'net_income', 'cash', 'debt', 'employees')),
  value          DOUBLE,
  unit           VARCHAR,
  period_start   DATE,
  period_end     DATE,
  form           VARCHAR,
  concept        VARCHAR,
  missing_reason VARCHAR,
  source VARCHAR NOT NULL, as_of DATE NOT NULL, license VARCHAR NOT NULL, retrieved TIMESTAMP NOT NULL,
  confidence VARCHAR NOT NULL CHECK (confidence IN ('high', 'medium', 'low')),
  PRIMARY KEY (company_id, metric),
  CHECK ((value IS NULL) <> (missing_reason IS NULL))
);
