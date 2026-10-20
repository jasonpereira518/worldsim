import { connection } from 'next/server';
import { proxy, unavailable } from '@/lib/simProxy';

export async function GET() {
  await connection();
  return (await proxy('/feeds/live')) ?? unavailable();
}
