import { proxy, unavailable } from '@/lib/simProxy';

export async function GET(_req: Request, ctx: { params: Promise<{ id: string; other: string }> }) {
  const { id, other } = await ctx.params;
  return (await proxy(`/runs/${encodeURIComponent(id)}/compare/${encodeURIComponent(other)}`)) ?? unavailable();
}
