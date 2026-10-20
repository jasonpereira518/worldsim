import { Suspense } from 'react';
import App from '@/components/App';

async function Shared({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <App initialRunId={id} readOnly />;
}

/** Read-only shared link: replays the saved seed and configuration. */
export default function SharedRunPage({ params }: { params: Promise<{ id: string }> }) {
  return (
    <Suspense fallback={<div className="p-4 text-[12px] text-muted">Loading shared run…</div>}>
      <Shared params={params} />
    </Suspense>
  );
}
