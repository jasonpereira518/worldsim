'use client';
// Ensemble band of the key metric: 90% interval (light), 50% interval (mid), median line, optional playhead.
import { fmtNum } from './format';

export default function BandChart({ bands, total, playhead, height = 36, unit, compareBands }: {
  bands: (number[] | null | undefined)[]; total: number; playhead?: number; height?: number; unit?: string; compareBands?: (number[] | null | undefined)[];
}) {
  const W = 1000;
  const all = [...bands, ...(compareBands ?? [])].filter(Boolean) as number[][];
  if (!all.length) return null;
  const max = Math.max(...all.map((b) => b[4]), 1e-9);
  const x = (t: number) => (t / Math.max(total, 1)) * W;
  const y = (v: number) => height - 2 - (v / max) * (height - 4);
  const area = (bs: (number[] | null | undefined)[], lo: number, hi: number) => {
    const pts = bs.map((b, t) => (b ? [t, b] : null)).filter(Boolean) as [number, number[]][];
    if (!pts.length) return '';
    return `M${pts.map(([t, b]) => `${x(t)},${y(b[hi])}`).join(' L')} L${pts.reverse().map(([t, b]) => `${x(t)},${y(b[lo])}`).join(' L')} Z`;
  };
  const line = (bs: (number[] | null | undefined)[]) => {
    const pts = bs.map((b, t) => (b ? `${x(t)},${y(b[2])}` : null)).filter(Boolean);
    return pts.length ? `M${pts.join(' L')}` : '';
  };
  const cur = playhead != null ? bands[Math.min(playhead, bands.length - 1)] : null;
  return (
    <div className="relative">
      <svg viewBox={`0 0 ${W} ${height}`} preserveAspectRatio="none" className="block w-full" style={{ height }} role="img"
        aria-label={cur ? `Median ${fmtNum(cur[2])} ${unit ?? ''}, 90% interval ${fmtNum(cur[0])} to ${fmtNum(cur[4])}` : 'Ensemble band'}>
        <path d={area(bands, 0, 4)} fill="var(--gray-2)" opacity={0.45} />
        <path d={area(bands, 1, 3)} fill="var(--muted)" opacity={0.45} />
        <path d={line(bands)} fill="none" stroke="var(--ink)" strokeWidth={1.5} vectorEffect="non-scaling-stroke" />
        {compareBands && <path d={line(compareBands)} fill="none" stroke="var(--ink)" strokeWidth={1.5} strokeDasharray="4 3" vectorEffect="non-scaling-stroke" />}
        {playhead != null && <line x1={x(playhead)} x2={x(playhead)} y1={0} y2={height} stroke="var(--ink)" strokeWidth={1} strokeDasharray="2 2" vectorEffect="non-scaling-stroke" />}
      </svg>
      {cur && (
        <div className="num pointer-events-none absolute left-1 top-0 text-[10px] text-muted">
          median {fmtNum(cur[2])} · 90% {fmtNum(cur[0])}–{fmtNum(cur[4])} {unit}
        </div>
      )}
    </div>
  );
}
