'use client';
import Link from 'next/link';
import { useEffect, useState } from 'react';
import type { Report } from '@/lib/sim/types';
import BandChart from '../BandChart';
import ScaleCard from '../ScaleCard';
import { fmtNum } from '../format';
import ReportMap from './ReportMap';
import { layout, wrap } from './causal';

/** Actor policies: the agent chose action, scope and central values; the engine decided when each fired in every run. */
function WhoDecided({ d }: { d: NonNullable<Report['decisions']> }) {
  const a = d.adaptation;
  return (
    <div className="mt-4">
      {d.policies.length > 0 && <>
      <h3 className="mb-1 text-[12px] font-medium">Who decided what</h3>
      <p className="mb-2 text-[11px] text-muted">Conditional policies chosen by the actors agent. The engine decides when each one fires in every run.</p>
      <ul className="space-y-1.5">
        {d.policies.map((p) => (
          <li key={p.id}>
            <span className="font-medium">{p.actor}</span>: {p.action} <span className="text-muted">({p.scope.replace('group:', '')})</span> when {p.trigger}, after{' '}
            <span className="num">{fmtNum(p.lag_days)}</span> days.{' '}
            <span className="text-muted">
              Fired in <span className="num">{p.fired_runs}</span> of <span className="num">{p.n}</span> runs
              {p.median_day != null && <>, median day <span className="num">{Math.round(p.median_day)}</span></>}.
            </span>
            {p.rationale && <> {p.rationale}</>}
            {p.revised && <span className="ml-1 text-[10px] text-muted">revised after the first look</span>}
          </li>
        ))}
      </ul>
      {a && (
        <p className="mt-2 text-[11px] text-muted">
          Re-plan: after a first look at <span className="num">{a.n}</span> runs the actors {a.revised ? 'revised' : 'kept'} their plan. Over those runs the median{' '}
          {a.name.toLowerCase()} went from <span className="num">{fmtNum(a.before)}</span> to <span className="num">{fmtNum(a.after)}</span> {a.unit}.
        </p>
      )}
      </>}
      {d.crowds && d.crowds.length > 0 && (
        <>
          <h3 className="mb-1 mt-3 text-[12px] font-medium">How populations behave</h3>
          <p className="mb-2 text-[11px] text-muted">Stances from the crowds agent, relative to the model&apos;s typical behavior. Each label maps to a range the ensemble samples.</p>
          <ul className="space-y-1">
            {d.crowds.map((c) => (
              <li key={c.label}>
                <span className="font-medium">{c.label}</span>: {Object.entries(c.stances).map(([k, v]) => `${k}: ${v}`).join('; ')}.
                {c.rationale && <span className="text-muted"> {c.rationale}</span>}
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}

const H = ({ n, children }: { n: number; children: React.ReactNode }) => (
  <h2 className="mt-10 mb-3 break-after-avoid border-b border-line pb-1 text-[15px] font-medium"><span className="num mr-2 text-muted">{n}.</span>{children}</h2>
);

function Causal({ g }: { g: Report['causal'] }) {
  if (!g?.nodes?.length) return <p className="text-muted">No causal graph for this module.</p>;
  const { nodes, back, cols, rows } = layout(g);
  const BW = 170, BH = 64, GX = 60, GY = 22;
  const W = cols * BW + (cols - 1) * GX + 20, Hh = rows * BH + (rows - 1) * GY + 40;
  const pos = new Map(nodes.map((n) => [n.id, { x: 10 + n.col * (BW + GX), y: 10 + n.row * (BH + GY) }]));
  return (
    <svg viewBox={`0 0 ${W} ${Hh}`} className="w-full" role="img" aria-label="Causal chain">
      <defs><marker id="arr" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="var(--ink)" /></marker></defs>
      {g.edges.map((e, i) => {
        const a = pos.get(e.from), b = pos.get(e.to);
        if (!a || !b) return null;
        const isBack = back.has(`${e.from}>${e.to}`);
        const x1 = a.x + BW, y1 = a.y + BH / 2, x2 = b.x, y2 = b.y + BH / 2;
        const d = isBack ? `M${a.x + BW / 2},${a.y + BH} C${a.x + BW / 2},${Hh - 4} ${b.x + BW / 2},${Hh - 4} ${b.x + BW / 2},${b.y + BH}` : `M${x1},${y1} C${x1 + GX / 2},${y1} ${x2 - GX / 2},${y2} ${x2},${y2}`;
        return (
          <g key={i}>
            <path d={d} fill="none" stroke="var(--ink)" strokeWidth={1} strokeDasharray={isBack ? '4 3' : undefined} markerEnd="url(#arr)" />
            {e.label && <text x={isBack ? (a.x + b.x + BW) / 2 : (x1 + x2) / 2} y={isBack ? Hh - 6 : (y1 + y2) / 2 - 4} textAnchor="middle" fontSize={10} fill="var(--muted)">{e.label}</text>}
          </g>
        );
      })}
      {nodes.map((n) => {
        const p = pos.get(n.id)!;
        const lines = wrap(n.label, 26);
        return (
          <g key={n.id}>
            <rect x={p.x} y={p.y} width={BW} height={BH} rx={10} fill="var(--bg)" stroke="var(--ink)" />
            {lines.map((l, i) => <text key={i} x={p.x + BW / 2} y={p.y + BH / 2 + (i - (lines.length - 1) / 2) * 13 + 4} textAnchor="middle" fontSize={11} fill="var(--ink)">{l}</text>)}
          </g>
        );
      })}
    </svg>
  );
}

function Tornado({ rows }: { rows: Report['sensitivities'] }) {
  if (!rows.length) return null;
  const all = rows.flatMap((r) => [r.outcome_low, r.outcome_high, r.outcome_central]);
  const lo = Math.min(...all), hi = Math.max(...all), span = hi - lo || 1;
  const X = (v: number) => ((v - lo) / span) * 100;
  return (
    <div className="space-y-2">
      {rows.map((r) => (
        <div key={r.key} className="grid grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)] items-center gap-3">
          <div className="text-[11px]">{r.text} <span className="num text-muted">({r.low}–{r.high} {r.unit})</span></div>
          <div className="relative h-4">
            <div className="absolute top-1/2 h-[1px] w-full bg-line" />
            <div className="absolute top-0 h-4 bg-muted/60" style={{ left: `${Math.min(X(r.outcome_low), X(r.outcome_high))}%`, width: `${Math.abs(X(r.outcome_high) - X(r.outcome_low))}%` }} />
            <div className="absolute top-0 h-4 w-[2px] bg-ink" style={{ left: `${X(r.outcome_central)}%` }} />
            <span className="num absolute -bottom-3 text-[9px] text-muted" style={{ left: `${Math.min(X(r.outcome_low), X(r.outcome_high))}%` }}>{fmtNum(Math.min(r.outcome_low, r.outcome_high))}</span>
            <span className="num absolute -bottom-3 text-[9px] text-muted" style={{ left: `${Math.max(X(r.outcome_low), X(r.outcome_high))}%` }}>{fmtNum(Math.max(r.outcome_low, r.outcome_high))}</span>
          </div>
        </div>
      ))}
      <p className="pt-2 text-[10px] text-muted">Bars: key outcome with each assumption at the low and high end of its range, others central. Line: central run.</p>
    </div>
  );
}

function Table({ rows }: { rows: Record<string, string | number | null>[] }) {
  if (!rows?.length) return null;
  const cols = Object.keys(rows[0]);
  return (
    <table className="w-full text-[11px]">
      <thead><tr className="text-left text-[10px] text-muted">{cols.map((c) => <th key={c} className="py-1 pr-2 font-normal">{c.replace(/_/g, ' ')}</th>)}</tr></thead>
      <tbody>{rows.map((r, i) => <tr key={i} className="border-t border-line">{cols.map((c) => <td key={c} className={`py-1 pr-2 ${typeof r[c] === 'number' ? 'num' : ''}`}>{typeof r[c] === 'number' ? fmtNum(r[c] as number) : String(r[c] ?? '–')}</td>)}</tr>)}</tbody>
    </table>
  );
}

export default function ReportView({ runId }: { runId: string }) {
  const [r, setR] = useState<Report | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    fetch(`/api/runs/${encodeURIComponent(runId)}/report`).then(async (res) => (res.ok ? setR(await res.json()) : setError(`Report unavailable (${res.status}).`))).catch(() => setError('Report unavailable.'));
  }, [runId]);
  if (error) return <main className="mx-auto max-w-3xl p-6 text-[13px]">{error} <Link className="underline" href="/">Back</Link></main>;
  if (!r) return <main className="mx-auto max-w-3xl p-6 text-[13px] text-muted">Building the report (the ensemble and sensitivity runs may take a few seconds)…</main>;
  const g = r.geography;
  const run = r.appendix.run as Record<string, unknown>;
  return (
    <main className="report mx-auto max-w-3xl overflow-y-auto px-6 pb-16 pt-8 text-[13px] leading-relaxed print:max-w-none print:px-0" style={{ height: '100vh' }}>
      <div className="flex items-center gap-2 print:hidden">
        <a className="text-[12px] underline" href={`/?run=${r.run_id}`}>← Back to the run</a>
        <span className="flex-1" />
        <a className="rounded-full border border-line px-3 py-1 text-[12px] hover:bg-surface" href={`/api/runs/${r.run_id}/report.md`}>Download Markdown</a>
        <button className="rounded-full bg-ink px-3 py-1 text-[12px] text-bg" onClick={() => window.print()}>Print / Save PDF</button>
      </div>
      <header className="mt-6">
        <div className="text-[10px] uppercase tracking-wide text-muted">Worldsim report · {r.module} module · {r.confidence.overall} confidence</div>
        <h1 className="mt-1 text-[22px] font-semibold leading-tight">{r.title}</h1>
        <p className="mt-1 text-muted">Prompt: “{r.prompt}” · <span className="num">{r.start_date} → {r.end_date}</span> · generated <span className="num">{r.generated_at.slice(0, 16).replace('T', ' ')} UTC</span></p>
        <p className="mt-2 rounded-lg border border-line p-2 text-[11px]">{r.disclaimer}</p>
      </header>

      <H n={1}>Headline</H>
      <p className="text-[15px] leading-snug">{r.headline}</p>
      <div className="mt-3"><BandChart bands={r.series.band} total={r.series.band.length - 1} height={60} unit={r.series.unit} playhead={r.series.band.length - 1} /></div>

      <H n={2}>Scale and plausibility</H>
      {r.scale ? <ScaleCard scale={r.scale} full /> : <p className="text-muted">Not assessed for this run.</p>}

      <H n={3}>Key outcomes</H>
      <table className="w-full text-[12px]">
        <thead><tr className="text-left text-[10px] text-muted"><th className="py-1 font-normal">Outcome</th><th className="py-1 text-right font-normal">Median</th><th className="py-1 text-right font-normal">50% interval</th><th className="py-1 text-right font-normal">90% interval</th><th className="py-1 pl-2 font-normal">Unit</th><th className="py-1 font-normal">Confidence</th></tr></thead>
        <tbody>{r.key_outcomes.map((m) => (
          <tr key={m.name} className="border-t border-line"><td className="py-1 pr-2">{m.name}</td><td className="num py-1 text-right">{fmtNum(m.value)}</td><td className="num py-1 text-right text-muted">{fmtNum(m.low50)}–{fmtNum(m.high50)}</td>
            <td className="num py-1 text-right text-muted">{fmtNum(m.low)}–{fmtNum(m.high)}</td><td className="py-1 pl-2 text-muted">{m.unit}</td><td className="py-1 text-muted">{m.confidence}</td></tr>
        ))}</tbody>
      </table>

      <H n={4}>Timeline of key moments</H>
      <ol className="space-y-1">{r.timeline.map((e, i) => (
        <li key={i} className="grid grid-cols-[110px_1fr] gap-2"><span className="num text-muted">{e.date} · d{e.day}</span><span><span className="font-medium">{e.title}.</span> <span className="text-muted">Cause: {e.cause}.{e.places.length ? ` Places: ${e.places.join(', ')}.` : ''}</span></span></li>
      ))}</ol>

      <H n={5}>Geographic breakdown</H>
      {g.layer && <p className="mb-2 text-muted">Final state, {g.layer.label.toLowerCase()} ({g.layer.unit}). Darker is higher.</p>}
      {g.layer && <ReportMap values={g.final_layers[g.layer.key] ?? {}} />}
      {!!g.top_by_layer.length && (
        <ol className="mt-3 grid grid-cols-2 gap-x-6 gap-y-0.5">{g.top_by_layer.map((t, i) => <li key={t.iso3} className="flex justify-between"><span><span className="num text-muted">{i + 1}.</span> {t.country}</span><span className="num">{fmtNum(t.value)}</span></li>)}</ol>
      )}
      {Object.entries(g.tables).map(([name, rows]) => rows.length ? (
        <div key={name} className="mt-4"><div className="mb-1 text-[10px] uppercase tracking-wide text-muted">{name.replace(/_/g, ' ')}</div><Table rows={rows} /></div>
      ) : null)}

      <H n={6}>Winners and losers</H>
      <div className="grid grid-cols-2 gap-6">
        {(['winners', 'losers'] as const).map((side) => (
          <div key={side}><div className="mb-1 text-[10px] uppercase tracking-wide text-muted">{side}</div>
            <ul className="space-y-1">{r.winners_losers[side].map((w, i) => <li key={i}><span className="font-medium">{w.name}</span>: {w.why}{w.detail ? <span className="text-muted"> ({w.detail})</span> : null}</li>)}
              {!r.winners_losers[side].length && <li className="text-muted">None identified.</li>}</ul>
          </div>
        ))}
      </div>

      <H n={7}>Voices</H>
      <div className="space-y-3">{r.voices.map((v, i) => (
        <blockquote key={i} className="rounded-xl border border-line p-3">
          <p className="text-[14px]">“{v.quote}”</p>
          <footer className="mt-1 text-[11px] text-muted">{v.kind === 'institution' ? '■' : '●'} {v.persona}, <span className="num">{v.date}</span>. Data: {v.data}.{v.generator === 'llm' ? ' Voiced by an LLM from these numbers.' : ''}</footer>
        </blockquote>
      ))}</div>

      <H n={8}>Causal chain</H>
      <Causal g={r.causal} />
      <p className="mt-1 text-[10px] text-muted">Dashed arrows are feedback loops.</p>

      <H n={9}>Sensitivities and risks</H>
      <Tornado rows={r.sensitivities} />

      <H n={10}>Decision points</H>
      <p className="mb-2 text-[11px] text-muted">Analysis of what would have changed the simulated outcome. Not a recommendation.</p>
      <ul className="space-y-1.5">{r.decision_points.map((d, i) => <li key={i}><span className="font-medium">{d.action}</span> <span className="text-muted">— when {d.trigger}.</span> {d.effect} <span className="text-[10px] text-muted">({d.basis})</span></li>)}</ul>
      {r.decisions && <WhoDecided d={r.decisions} />}

      <H n={11}>Confidence and limitations</H>
      <p>Overall: <span className="font-medium">{r.confidence.overall}</span>.</p>
      <ul className="mt-1 list-disc space-y-0.5 pl-5">
        {r.confidence.reasons.map((x, i) => <li key={`r${i}`}>{x}</li>)}
        {r.confidence.data_gaps.map((x, i) => <li key={`g${i}`}>Data gap: {x}</li>)}
        {r.confidence.stale_sources.map((x, i) => <li key={`s${i}`}>Stale source: {x}</li>)}
        <li>Calibration: {r.confidence.calibration}</li>
        {r.confidence.analogs?.map((a, i) => <li key={`a${i}`}>Analog: {a.name}. {a.outcomes} <span className="text-muted">({a.source})</span></li>)}
        {r.confidence.flags?.map((f, i) => (
          <li key={`f${i}`}>
            Flag: {f.text} <span className="text-[10px] text-muted">({f.kind.replace(/_/g, ' ')}{f.generator === 'llm' ? ', AI critic' : ''})</span>
          </li>
        ))}
      </ul>

      <H n={12}>Sources and assumptions</H>
      <table className="w-full text-[11px]">
        <thead><tr className="text-left text-[10px] text-muted"><th className="py-1 font-normal">Dataset</th><th className="py-1 font-normal">Source</th><th className="py-1 font-normal">As of</th><th className="py-1 font-normal">License</th></tr></thead>
        <tbody>{r.appendix.datasets.map((d) => <tr key={d.id} className="border-t border-line"><td className="py-1 pr-2">{d.name}</td><td className="py-1 pr-2">{d.source}</td><td className="num py-1 pr-2">{d.as_of ?? 'n/a'}</td><td className="py-1">{d.license}</td></tr>)}</tbody>
      </table>
      <table className="mt-4 w-full text-[11px]">
        <thead><tr className="text-left text-[10px] text-muted"><th className="py-1 font-normal">Assumption</th><th className="py-1 text-right font-normal">Value</th><th className="py-1 text-right font-normal">Range</th><th className="py-1 pl-2 font-normal">Origin</th><th className="py-1 font-normal">Confidence</th></tr></thead>
        <tbody>{r.appendix.assumptions.map((a, i) => (
          <tr key={`${a.id}-${i}`} className="border-t border-line" title={a.source ?? undefined}><td className="py-1 pr-2">{a.text}{a.source ? <span className="block text-[10px] text-muted">{a.source}</span> : null}</td>
            <td className="num py-1 text-right">{a.value ?? ''} {a.unit ?? ''}</td><td className="num py-1 text-right text-muted">{a.low != null && a.high != null && a.low !== a.high ? `${a.low}–${a.high}` : ''}</td>
            <td className="py-1 pl-2">{a.origin}</td><td className="py-1">{a.confidence}</td></tr>
        ))}</tbody>
      </table>
      <p className="mt-4 text-[10px] text-muted">Run <span className="num">{String(run.run_id)}</span> · seed <span className="num">{String(run.seed)}</span> · engine {String(run.engine)} · snapshot <span className="num">{String(run.snapshot)}</span> · ensemble {String(run.ensemble_size)} (median member {String(run.median_member)}) · parser {String(run.parser)}. Replaying this seed and configuration reproduces the run.</p>
    </main>
  );
}
