import { proxy, unavailable } from '@/lib/simProxy';

export async function GET(_req: Request, ctx: { params: Promise<{ id: string }> }) {
  const { id } = await ctx.params;
  const res = await proxy(`/runs/${encodeURIComponent(id)}/report.md`);
  if (!res) return unavailable();
  if (!res.ok) return res;
  return new Response(res.body, { headers: { 'content-type': 'text/markdown; charset=utf-8', 'content-disposition': `attachment; filename="worldsim-${id}.md"` } });
}
