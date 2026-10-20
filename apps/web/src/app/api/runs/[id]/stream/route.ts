import { createRun } from '@/lib/sim/engine';
import { runs } from '@/lib/sim/registry';
import type { Frame, ServerEvent } from '@/lib/sim/types';

const FRAME_DELAY_MS = 20; // emulates a real engine's pace so progress is visible

export async function GET(req: Request, ctx: { params: Promise<{ id: string }> }) {
  const { id } = await ctx.params;
  const config = runs.get(id);
  if (!config) return Response.json({ error: 'unknown run' }, { status: 404 });

  const encoder = new TextEncoder();
  const stream = new ReadableStream<Uint8Array>({
    async start(controller) {
      const send = (ev: ServerEvent) => controller.enqueue(encoder.encode(`event: ${ev.type}\ndata: ${JSON.stringify(ev)}\n\n`));
      try {
        const run = createRun(config.spec, config.seed);
        send({ type: 'personas', personas: run.personas });
        const total = Math.ceil(config.spec.horizon_days / config.spec.step_days);
        const all: Frame[] = [];
        for (const frame of run.frames()) {
          if (req.signal.aborted) return controller.close();
          all.push(frame);
          send({ type: 'frame', frame });
          if (frame.t % 5 === 0 || frame.t === total) send({ type: 'progress', t: frame.t, total, label: `Simulating day ${frame.t * config.spec.step_days} of ${config.spec.horizon_days}` });
          await new Promise((r) => setTimeout(r, FRAME_DELAY_MS));
        }
        send({ type: 'summary', summary: run.summary(all) });
        send({ type: 'done' });
      } catch (err) {
        send({ type: 'error', message: err instanceof Error ? err.message : 'engine failure' });
      }
      controller.close();
    },
  });
  return new Response(stream, {
    headers: { 'Content-Type': 'text/event-stream; charset=utf-8', 'Cache-Control': 'no-cache, no-transform', Connection: 'keep-alive', 'X-Accel-Buffering': 'no' },
  });
}
