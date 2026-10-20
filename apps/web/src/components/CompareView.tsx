'use client';
import { useEffect, useState } from 'react';
import { useStore } from '@/lib/store';
import type { CompareResult } from '@/lib/sim/types';
import BandChart from './BandChart';
import { fmtNum } from './format';

export default function CompareView() {
  const compare = useStore((s) => s.compare);
  const setCompare = useStore((s) => s.setCompare);
  // results are keyed by the pair, so a new pair shows "computing" without resetting state inside the effect
  const [result, setResult] = useState<{ key: string; data?: CompareResult; error?: string } | null>(null);
  const key = compare ? `${compare.a}|${compare.b}` : '';
  useEffect(() => {
    if (!compare) return;
    const k = `${compare.a}|${compare.b}`;
    fetch(`/api/runs/${compare.a}/compare/${compare.b}`)
      .then(async (r) => setResult(r.ok ? { key: k, data: await r.json() } : { key: k, error: `Comparison failed (${r.status})` }))
      .catch(() => setResult({ key: k, error: 'Comparison failed' }));
  }, [compare]);
  if (!compare) return null;
  const data = result?.key === key ? result.data ?? null : null;
  const error = result?.key === key ? result.error ?? null : null;
  const total = Math.max((data?.series.dates.length ?? 1) - 1, 1);
  return (
    <div className="fixed inset-0 z-40 flex items-start justify-center overflow-y-auto bg-bg/80 p-4 backdrop-blur-sm" role="dialog" aria-modal="true" aria-label="Compare runs"
      onKeyDown={(e) => e.key === 'Escape' && setCompare(null)}>
      <div className="w-full max-w-3xl rounded-xl border border-ink bg-bg p-4 text-[12px] fade-in">
        <div className="flex items-start gap-2">
          <div className="min-w-0 flex-1">
            <h2 className="text-[15px] font-medium">Compare runs</h2>
            {data && <p className="text-muted">Baseline <span className="num">{data.a.run_id}</span> vs branch <span className="num">{data.b.run_id}</span>{data.b.label ? `: ${data.b.label}` : ''}. Same seed, so differences come from the change.</p>}
          </div>
          <button autoFocus className="rounded-full border border-line px-2 py-0.5 hover:bg-surface" onClick={() => setCompare(null)} aria-label="Close comparison">✕</button>
        </div>
        {error && <p className="mt-3">{error}</p>}
        {!data && !error && <p className="mt-3 text-muted">Computing both runs…</p>}
        {data && (
          <>
            <div className="mt-3">
              <div className="mb-1 text-[10px] uppercase tracking-wide text-muted">Key metric over time · solid: baseline band and median · dashed: branch median</div>
              <BandChart bands={data.series.a} compareBands={data.series.b} total={total} height={80} unit={data.series.unit} />
            </div>
            <table className="mt-3 w-full text-[11px]">
              <thead><tr className="text-left text-[10px] text-muted"><th className="py-1 font-normal">Outcome</th><th className="py-1 text-right font-normal">Baseline</th><th className="py-1 text-right font-normal">Branch</th><th className="py-1 text-right font-normal">Change</th></tr></thead>
              <tbody>
                {data.metrics.map((m) => (
                  <tr key={m.name} className="border-t border-line">
                    <td className="py-1 pr-2">{m.name} <span className="text-[10px] text-muted">({m.unit})</span></td>
                    <td className="num py-1 text-right">{fmtNum(m.a)} <span className="text-muted">[{fmtNum(m.a_low)}–{fmtNum(m.a_high)}]</span></td>
                    <td className="num py-1 text-right">{fmtNum(m.b)} <span className="text-muted">[{fmtNum(m.b_low)}–{fmtNum(m.b_high)}]</span></td>
                    <td className="num py-1 text-right font-medium">{m.delta_pct == null ? fmtNum(m.delta) : `${m.delta_pct > 0 ? '+' : ''}${m.delta_pct.toFixed(1)}%`}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="mt-1 text-[10px] text-muted">Medians with 90% intervals in brackets. Overlapping intervals mean the change is within the ensemble&apos;s uncertainty.</p>
            {!!data.layer.deltas.length && (
              <div className="mt-3">
                <div className="mb-1 text-[10px] uppercase tracking-wide text-muted">Largest country changes · {data.layer.label}</div>
                <ul className="grid grid-cols-2 gap-x-4 gap-y-0.5">
                  {data.layer.deltas.map((d) => <li key={d.iso3} className="flex justify-between"><span>{d.country}</span><span className="num">{d.delta > 0 ? '+' : ''}{fmtNum(d.delta)}</span></li>)}
                </ul>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
