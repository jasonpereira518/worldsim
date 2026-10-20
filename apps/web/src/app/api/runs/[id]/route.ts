import { runs } from '@/lib/sim/registry';
import { proxy, unavailable } from '@/lib/simProxy';

export async function GET(_req: Request, ctx: { params: Promise<{ id: string }> }) {
  const { id } = await ctx.params;
  const mock = runs.get(id);
  if (mock) return Response.json(mock);
  return (await proxy(`/runs/${encodeURIComponent(id)}`)) ?? unavailable();
}
