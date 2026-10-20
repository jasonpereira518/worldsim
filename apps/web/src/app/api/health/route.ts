import { connection } from 'next/server';
import { proxy } from '@/lib/simProxy';

export async function GET() {
  await connection();
  return (await proxy('/health')) ?? Response.json({ ok: true, engine: 'mock-m0', note: 'sim service not reachable; using the Milestone 0 mock engine' });
}
