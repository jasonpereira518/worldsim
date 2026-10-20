import { connection } from 'next/server';
import { listCompanies, respond } from '@/lib/data/store';

export async function GET() {
  await connection(); // read the snapshot per request, never at build time
  return respond(() => listCompanies());
}
