import { getCompany, respond } from '@/lib/data/store';

/** GET /api/data/companies/apple → CompanyProfile. Also accepts a Wikidata QID, LEI, ticker, or unique id prefix. */
export async function GET(_req: Request, ctx: { params: Promise<{ id: string }> }) {
  const { id } = await ctx.params;
  if (!/^[\w.-]{1,64}$/.test(id)) return Response.json({ error: 'invalid company reference' }, { status: 400 });
  return respond(() => getCompany(id), `unknown company ${id}`);
}
