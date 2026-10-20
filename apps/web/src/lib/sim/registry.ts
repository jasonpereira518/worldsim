// In-memory run registry. Frames are recomputed from (seed, spec) on demand, so only the config is stored.
// ponytail: process memory; move to Postgres run_configs in M1.
import type { RunConfig } from './types';

const g = globalThis as unknown as { __worldsimRuns?: Map<string, RunConfig> };
export const runs: Map<string, RunConfig> = (g.__worldsimRuns ??= new Map());
export const DATA_SNAPSHOT = 'm0-natural-earth-5.1.1';
