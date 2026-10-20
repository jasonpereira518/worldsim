import { createRun } from '@/lib/sim/engine';
import { findPlace } from '@/lib/sim/parse';
import { runs } from '@/lib/sim/registry';
import type { ChatAction, SimEvent } from '@/lib/sim/types';

const M4 = 'Branching, comparison and re-runs arrive in Milestone 4. In this build you can ask "zoom into Brazil", "why did Turkey get hit", or use /assumptions, /sources and /reset.';

export async function POST(req: Request, ctx: { params: Promise<{ id: string }> }) {
  const { id } = await ctx.params;
  const config = runs.get(id);
  if (!config) return Response.json({ error: 'unknown run' }, { status: 404 });
  let body: { message?: unknown };
  try { body = await req.json(); } catch { return Response.json({ error: 'invalid JSON' }, { status: 400 }); }
  const message = typeof body.message === 'string' ? body.message.trim().slice(0, 500) : '';
  if (!message) return Response.json({ error: 'empty message' }, { status: 400 });

  const lower = message.toLowerCase();
  const place = findPlace(message);
  if (/\b(zoom|go to|show me|fly to|look at)\b/.test(lower) && place) {
    const action: ChatAction = { type: 'zoom', center: [place.lon, place.lat], zoom: place.pop > 5e6 ? 6 : 7 };
    return Response.json({ reply: `Zooming to ${place.name}, ${place.country}.`, action });
  }
  if (/\b(why|explain|how did|when did)\b/.test(lower)) {
    const run = createRun(config.spec, config.seed);
    const events: SimEvent[] = [];
    for (const f of run.frames()) events.push(...f.events);
    const hits = place ? events.filter((e) => e.title.includes(place.country) || e.places.includes(place.name)) : events.filter((e) => e.severity === 3).slice(0, 5);
    if (!hits.length) return Response.json({ reply: place ? `${place.country} was not reached at a notable level in this run.` : 'No notable moments were logged in this run.' });
    return Response.json({ reply: hits.map((e) => `${e.date} (day ${e.t * config.spec.step_days}): ${e.title}. Cause: ${e.cause}.`).join('\n') + '\n\nMock engine: causes are diffusion steps, not calibrated mechanisms.' });
  }
  return Response.json({ reply: M4 });
}
