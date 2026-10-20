import { getCountry, respond } from '@/lib/data/store';

/** GET /api/data/countries/VNM[?series=1] → CountryProfile */
export async function GET(req: Request, ctx: { params: Promise<{ iso3: string }> }) {
  const { iso3 } = await ctx.params;
  if (!/^[A-Za-z]{3}$/.test(iso3)) return Response.json({ error: 'iso3 must be an ISO 3166-1 alpha-3 code' }, { status: 400 });
  const series = new URL(req.url).searchParams.get('series') === '1';
  return respond(() => getCountry(iso3, { series }), `unknown country ${iso3.toUpperCase()}`);
}
