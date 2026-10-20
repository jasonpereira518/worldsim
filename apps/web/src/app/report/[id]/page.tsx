import { Suspense } from 'react';
import ReportView from '@/components/report/ReportView';

async function Report({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <ReportView runId={id} />;
}

export default function ReportPage({ params }: { params: Promise<{ id: string }> }) {
  return (
    <Suspense fallback={<div className="p-6 text-[12px] text-muted">Loading report…</div>}>
      <Report params={params} />
    </Suspense>
  );
}
