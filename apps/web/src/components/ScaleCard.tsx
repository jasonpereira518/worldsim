'use client';
import type { EscalationBranch, Plausibility, ReachClass, ScaleHypothesis, ScaleReport } from '@/lib/sim/types';
import { fmtNum } from './format';

type Sized = ScaleReport['branches'][number];

const REACH: ReachClass[] = ['local', 'regional', 'national', 'multi_country', 'global'];
const LABEL: Record<ReachClass, string> = { local: 'Local', regional: 'Regional', national: 'National', multi_country: 'Multi-country', global: 'Global' };
const SHORT: Record<ReachClass, string> = { local: 'Local', regional: 'Region', national: 'Nation', multi_country: 'Multi', global: 'Global' };
// Monochrome: severity by fill, never hue. Solid ink = the premise has a problem; outline = at the edge of the record.
const VERDICT: Record<Plausibility['verdict'], string> = { realistic: 'border border-line text-muted', stretched: 'border border-ink', implausible: 'bg-ink text-bg', impossible: 'bg-ink text-bg' };

const short = (name: string) => name.split(' (')[0].replace(/,.*$/, '').replace(/ (influenza )?(earthquakes?|pandemic|epidemic|launch)( and tsunami)?$/i, '');

function ReachBar({ dist, forecast }: { dist: Record<ReachClass, number>; forecast?: ReachClass }) {
  return (
    <div className="grid grid-cols-5 gap-0.5" role="img" aria-label={`Measured reach: ${REACH.map((r) => `${LABEL[r]} ${Math.round(dist[r] * 100)}%`).join(', ')}${forecast ? `; forecast ${LABEL[forecast]}` : ''}`}>
      {REACH.map((r) => {
        const share = dist[r] ?? 0;
        return (
          <div key={r} title={`${LABEL[r]}${r === forecast ? ' (forecast)' : ''}`} className={`rounded px-0.5 py-1 text-center ${r === forecast ? 'outline outline-2 -outline-offset-2 outline-ink' : ''}`}
            style={{ background: `color-mix(in srgb, var(--ink) ${Math.round(share * 100)}%, var(--bg))`, color: share > 0.5 ? 'var(--bg)' : 'var(--ink)' }}>
            <div className="text-[9px]">{SHORT[r]}</div>
            <div className="num text-[11px]">{share ? `${Math.round(share * 100)}%` : '–'}</div>
          </div>
        );
      })}
    </div>
  );
}

/** Log-scale ladder: historical analogs (ticks) and the simulated 5th–95th percentile (band) with its median (dot). */
function Ladder({ rows, sim }: { rows: ScaleReport['measurement']['magnitude']; sim: { p5: number; p50: number; p95: number } }) {
  const vals = [...rows.map((r) => r.value), sim.p5, sim.p95].filter((v) => v > 0);
  if (!vals.length) return null;
  const lo = Math.log10(Math.min(...vals) / 2), hi = Math.log10(Math.max(...vals) * 2);
  const x = (v: number) => 8 + ((Math.log10(Math.max(v, 1e-9)) - lo) / (hi - lo || 1)) * 304;
  // greedy lanes: each label takes the first row where it clears the previous label (≈4.4 units per character at size 8)
  const ends: number[] = [];
  const labels = rows.map((r) => ({ r, cx: x(r.value), text: short(r.name) })).sort((a, b) => a.cx - b.cx).map((l) => {
    const half = l.text.length * 2.2 + 3;
    const left = Math.max(l.cx - half, 0);
    let lane = ends.findIndex((end) => left > end);
    if (lane < 0) lane = ends.push(0) - 1;
    ends[lane] = Math.min(l.cx + half, 320);
    return { ...l, lane, anchor: (l.cx < half ? 'start' : l.cx > 320 - half ? 'end' : 'middle') as 'start' | 'end' | 'middle' };
  });
  const axis = 14 + ends.length * 10;
  return (
    <svg viewBox={`0 0 320 ${axis + 16}`} className="mt-1 block w-full" role="img" aria-label="Simulated outcome compared with past events on a log scale">
      <line x1={8} x2={312} y1={axis} y2={axis} stroke="var(--line)" />
      <rect x={x(sim.p5)} y={axis - 4} width={Math.max(x(sim.p95) - x(sim.p5), 2)} height={8} fill="var(--gray-2)" />
      <circle cx={x(sim.p50)} cy={axis} r={3.5} fill="currentColor" />
      {labels.map((l) => (
        <g key={l.r.analog_id}>
          <line x1={l.cx} x2={l.cx} y1={12 + l.lane * 10} y2={axis + 6} stroke="currentColor" strokeWidth={0.75} />
          <text x={l.cx} y={9 + l.lane * 10} fontSize={8} textAnchor={l.anchor} fill="currentColor">{l.text}</text>
        </g>
      ))}
      <text x={x(sim.p50)} y={axis + 14} fontSize={7.5} textAnchor="middle" fill="var(--muted)">simulated median</text>
    </svg>
  );
}

export default function ScaleCard({ plausibility, hypothesis, scale, full = false }:
  { plausibility?: Plausibility | null; hypothesis?: ScaleHypothesis | null; scale?: ScaleReport | null; full?: boolean }) {
  const p = scale?.plausibility ?? plausibility ?? null;
  const hyp = scale?.hypothesis ?? hypothesis ?? null;
  const m = scale?.measurement;
  const headline = m ? m.magnitude.filter((r) => r.metric === m.headline_metric) : [];
  const countries = m?.reach.countries;
  return (
    <div className={full ? 'text-[13px]' : 'rounded-xl border border-line bg-surface p-3 text-[12px] fade-in'}>
      {!full && (
        <div className="mb-1.5 flex flex-wrap items-baseline gap-2">
          <span className="font-medium">Scale</span>
          <span className="text-[11px] text-muted">{m ? 'measured by the engine' : 'measuring…'}{hyp?.generator === 'llm' ? ' · forecast by the scale assessor (AI), recorded before the numbers' : ''}</span>
        </div>
      )}
      {full && scale?.narrative && <p className="mb-3">{scale.narrative}</p>}
      <dl className={`grid gap-x-2 gap-y-2 ${full ? 'grid-cols-[100px_1fr]' : 'grid-cols-[72px_1fr]'}`}>
        <dt className="text-muted">Plausibility</dt>
        <dd>
          {p ? (
            <>
              <span className={`mr-1.5 inline-block rounded-full px-1.5 py-px text-[10px] uppercase tracking-wide ${VERDICT[p.verdict]}`}>{p.verdict}</span>
              <span className="text-[11px] text-muted">{p.generator === 'llm' ? 'intake analyst (AI)' : 'physical-limit rules'}</span>
              {!!p.reasons?.length && <p className="mt-0.5">{p.reasons.join(' ')}</p>}
              {p.adjusted_premise && <p className="mt-0.5 text-muted">Suggested premise: “{p.adjusted_premise}”</p>}
            </>
          ) : <span className="text-muted">Not judged: AI check off, no physical-limit rule applies.</span>}
        </dd>

        <dt className="text-muted">Reach</dt>
        <dd>
          {m ? (
            <>
              <ReachBar dist={m.reach.distribution} forecast={hyp?.reach_expected} />
              <p className="mt-1">
                Mostly <span className="font-medium">{LABEL[m.reach.mode].toLowerCase()}</span> ({Math.round(m.reach.distribution[m.reach.mode] * 100)}% of runs)
                {countries ? <>; countries materially affected <span className="num">{Math.round(countries.p50)}</span> <span className="text-muted">(90% interval <span className="num">{Math.round(countries.p5)}–{Math.round(countries.p95)}</span>)</span></> : null}.
              </p>
              {m.forecast && (
                <p className="text-muted">Forecast {LABEL[m.forecast.reach_expected].toLowerCase()}: {m.forecast.reach_hit ? 'matched the measurement' : `measured in ${Math.round(m.forecast.reach_share * 100)}% of runs`}.</p>
              )}
            </>
          ) : hyp ? (
            <p>Forecast <span className="font-medium">{LABEL[hyp.reach_expected].toLowerCase()}</span>. {hyp.reach_why}</p>
          ) : <span className="text-muted">Measured when the ensemble finishes.</span>}
        </dd>

        <dt className="text-muted">Magnitude</dt>
        <dd>
          {m ? (
            <>
              <p>{m.position}</p>
              {full && headline.length > 0 && <Ladder rows={headline} sim={headline[0].sim} />}
              {full && m.magnitude.length > 0 && (
                <table className="mt-2 w-full text-[12px]">
                  <thead><tr className="text-left text-[11px] text-muted"><th className="py-1 font-normal">Past event</th><th className="py-1 font-normal">Metric</th><th className="py-1 text-right font-normal">Recorded</th><th className="py-1 text-right font-normal">Simulated (90%)</th><th className="py-1 pl-2 font-normal">Band</th></tr></thead>
                  <tbody>
                    {m.magnitude.map((r) => (
                      <tr key={`${r.analog_id}-${r.metric}`} className="border-t border-line align-top" title={`${r.source}${r.definition ? `; ${r.definition}` : ''}`}>
                        <td className="py-1 pr-2">{r.name}</td><td className="py-1 pr-2 text-muted">{r.metric_name}</td>
                        <td className="num py-1 text-right">{fmtNum(r.value)}</td>
                        <td className="num py-1 text-right">{fmtNum(r.sim.p50)} <span className="text-muted">({fmtNum(r.sim.p5)}–{fmtNum(r.sim.p95)})</span></td>
                        <td className="py-1 pl-2">{r.band}{r.inside_90 ? '' : <span className="text-muted"> · outside range</span>}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </>
          ) : <span className="text-muted">Compared with past events when the ensemble finishes.</span>}
        </dd>

        {(scale?.branches?.length || hyp?.branches?.length) ? (
          <>
            <dt className="text-muted">Escalation</dt>
            <dd>
              <ul className="space-y-1.5">
                {(scale?.branches ?? hyp?.branches ?? []).map((b: EscalationBranch) => {
                  const sized = scale?.branches ? (b as Sized) : null;  // measured paths carry their computed size
                  return (
                    <li key={b.id}>
                      <span className="font-medium">{b.title}</span>
                      {full && <span className="text-muted"> · {b.path}; trigger: {b.trigger}</span>}
                      {sized?.size && (
                        <div className="text-[11px]">
                          median <span className="num">{fmtNum(sized.size.p50)}</span> <span className="text-muted">(<span className="num">{fmtNum(sized.size.p5)}–{fmtNum(sized.size.p95)}</span>)</span>
                          {sized.exceedance && <> · <span className="num">{sized.exceedance.k} of {sized.exceedance.n}</span> base runs reach {sized.exceedance.direction} this ({sized.computed_likelihood})</>}
                        </div>
                      )}
                      {b.likelihood && <div className="text-[11px] text-muted">judged {b.likelihood} by the scale assessor</div>}
                    </li>
                  );
                })}
              </ul>
            </dd>
          </>
        ) : null}
      </dl>
      <p className="mt-2 text-[10px] text-muted">Reach, magnitude and path sizes are computed from the simulation ensemble; AI judgments are labels scored against them. Past events: {m ? `${new Set(m.magnitude.map((r) => r.analog_id)).size} comparable in the library` : 'library of recorded outcomes'}.</p>
    </div>
  );
}
