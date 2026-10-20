/** Compact number for UI: 1.2B, 3.4M, 56k, 789, 1.23. */
export function fmtNum(v: number | null | undefined, unit?: string): string {
  if (v == null || !Number.isFinite(v)) return '–';
  const a = Math.abs(v);
  const s = a >= 1e9 ? `${(v / 1e9).toFixed(2)}B` : a >= 1e6 ? `${(v / 1e6).toFixed(1)}M` : a >= 1e4 ? `${Math.round(v / 1e3)}k` : a >= 100 ? Math.round(v).toLocaleString() : a >= 1 ? v.toFixed(1) : v.toPrecision(2);
  return unit === '%' ? `${s}%` : s;
}
