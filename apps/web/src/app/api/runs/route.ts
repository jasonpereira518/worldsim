import { connection } from 'next/server';
import { parsePrompt } from '@/lib/sim/parse';
import { fnv1a } from '@/lib/sim/prng';
import { DATA_SNAPSHOT, runs } from '@/lib/sim/registry';
import type { RunConfig } from '@/lib/sim/types';
import { proxy } from '@/lib/simProxy';

/** Run history from the sim service (empty when only the mock engine is available). */
export async function GET() {
  await connection();
  return (await proxy('/runs')) ?? Response.json([...runs.values()].map((c) => ({ run_id: c.run_id, title: c.spec.title, created_at: c.created_at, parent_run_id: null, label: null, module: 'mock', seed: c.seed })));
}

export async function POST(req: Request) {
  const text = await req.text();
  const viaService = await proxy('/runs', { method: 'POST', body: text });
  if (viaService) return viaService;
  // Fallback: Milestone 0 mock engine, labeled engine 'mock-m0'.
  let body: { prompt?: unknown; answers?: { origin?: unknown }; seed?: unknown };
  try { body = JSON.parse(text); } catch { return Response.json({ error: 'invalid JSON' }, { status: 400 }); }
  const prompt = typeof body.prompt === 'string' ? body.prompt.trim() : '';
  if (!prompt || prompt.length > 500) return Response.json({ error: 'prompt must be 1-500 characters' }, { status: 400 });
  const origin = typeof body.answers?.origin === 'string' ? body.answers.origin.slice(0, 100) : undefined;
  const seed = typeof body.seed === 'number' && Number.isFinite(body.seed) ? body.seed >>> 0 : fnv1a(prompt + (origin ?? ''));
  const spec = parsePrompt(prompt, { origin });
  const run_id = `mock_${Date.now().toString(36)}_${seed.toString(36)}`;
  const config: RunConfig = { run_id, seed, spec, created_at: new Date().toISOString(), data_snapshot: DATA_SNAPSHOT };
  runs.set(run_id, config);
  return Response.json({ run_id, spec }, { status: 201 });
}
