import { proxy, unavailable } from '@/lib/simProxy';

export async function GET(_req: Request, ctx: { params: Promise<{ id: string }> }) {
  const { id } = await ctx.params;
  return (await proxy(`/runs/${encodeURIComponent(id)}/report`)) ?? unavailable();
}
