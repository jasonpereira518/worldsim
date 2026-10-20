import { getCountryShapes, respond } from '@/lib/data/store';

export async function GET() {
  const res = await respond(() => getCountryShapes());
  res.headers.set('cache-control', 'public, max-age=3600');
  return res;
}
