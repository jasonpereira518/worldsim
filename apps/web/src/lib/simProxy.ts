// Forwards /api/* calls to the Python sim service (services/sim). Returns null when the service is unreachable,
// so the caller can fall back to the Milestone 0 mock engine, which labels itself `engine: 'mock-m0'` in the UI.
export const SIM_URL = process.env.SIM_SERVICE_URL ?? 'http://127.0.0.1:8731';

export async function proxy(path: string, init: { method?: string; body?: string; signal?: AbortSignal } = {}): Promise<Response | null> {
  let res: Response;
  try {
    res = await fetch(`${SIM_URL}${path}`, {
      method: init.method ?? 'GET',
      headers: init.body ? { 'content-type': 'application/json' } : undefined,
      body: init.body,
      signal: init.signal,
      cache: 'no-store',
    });
  } catch {
    return null;
  }
  const headers = new Headers({ 'content-type': res.headers.get('content-type') ?? 'application/json', 'x-worldsim-engine': 'sim-service' });
  if (headers.get('content-type')?.includes('event-stream')) {
    headers.set('cache-control', 'no-cache, no-transform');
    headers.set('x-accel-buffering', 'no');
  }
  return new Response(res.body, { status: res.status, headers });
}

export const unavailable = () => Response.json({ error: 'The simulation service is not running. Start it with `npm run sim` (see README).' }, { status: 503 });
