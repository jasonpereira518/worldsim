import { runs } from '@/lib/sim/registry';

export async function GET(_req: Request, ctx: { params: Promise<{ id: string }> }) {
  const { id } = await ctx.params;
  const config = runs.get(id);
  return config ? Response.json(config) : Response.json({ error: 'unknown run' }, { status: 404 });
}
