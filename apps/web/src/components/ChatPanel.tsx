'use client';
import Link from 'next/link';
import { useEffect, useRef, useState } from 'react';
import { useStore, type ChatMessage } from '@/lib/store';
import { EXAMPLES, editAssumption, loadLive, loadRun, refreshHistory, shareLink, submitPrompt } from '@/lib/runClient';
import { basisLabel, tierOf, type Assumption, type RunListItem, type ScenarioSpec, type SimEvent, type Summary } from '@/lib/sim/types';
import ScaleCard from './ScaleCard';
import VoicesLog from './VoicesLog';
import { fmtNum } from './format';

export { fmtNum };

function Chip({ a, editable }: { a: Assumption; editable: boolean }) {
  const [editing, setEditing] = useState(false);
  const [val, setVal] = useState(String(a.value ?? ''));
  const numeric = typeof a.value === 'number';
  const canEdit = editable && numeric && a.editable !== false && a.id !== 't0';
  const guess = tierOf(a) === 'guess';
  const title = `${basisLabel(a)}${guess ? ' (no official or peer-reviewed source sets this value)' : ''} · origin: ${a.origin} · ${a.confidence} confidence${a.source ? ` · ${a.source}` : ''}${a.low != null && a.high != null && a.low !== a.high ? ` · range ${a.low}–${a.high}` : ''}${canEdit ? ' · click to edit and branch' : ''}`;
  if (editing) {
    return (
      <form className="inline-flex items-center gap-1 rounded-full border border-ink bg-bg px-2 py-0.5 text-[11px]" onSubmit={(e) => { e.preventDefault(); const v = Number(val); setEditing(false); if (Number.isFinite(v) && v !== a.value) void editAssumption(a.id, v); }}>
        <span className="text-muted">{a.id}</span>
        <input autoFocus aria-label={`New value for ${a.text}`} className="num w-16 bg-transparent outline-none" value={val} onChange={(e) => setVal(e.target.value)} onBlur={() => setEditing(false)} inputMode="decimal" />
        <span className="text-muted">{a.unit}</span>
      </form>
    );
  }
  return (
    <button type="button" disabled={!canEdit} onClick={() => setEditing(true)} title={title}
      className={`rounded-full border px-2 py-0.5 text-left text-[11px] ${a.origin === 'user' ? 'border-ink' : 'border-line'} ${guess ? 'border-dashed' : ''} ${canEdit ? 'hover:bg-surface' : 'cursor-default'} bg-bg`}>
      {a.text}{numeric && a.id !== 'horizon_days' && !a.text.includes(String(a.value)) ? <span className="num text-muted"> = {String(a.value)}{a.unit ? ` ${a.unit}` : ''}</span> : null}
      <span className="ml-1 text-[9px] uppercase tracking-wide text-muted">{basisLabel(a)}</span>
    </button>
  );
}

function SpecCard({ spec, runId }: { spec: ScenarioSpec; runId?: string }) {
  const current = useStore((s) => s.runId);
  const report = useStore((s) => s.report);
  const readOnly = useStore((s) => s.readOnly);
  const isCurrent = runId === current;
  // model priors from the report (all editable numeric assumptions) once the run is done; parser assumptions before that
  const extra = isCurrent && report ? report.appendix.assumptions.filter((a) => a.editable && !spec.assumptions.some((b) => b.id === a.id)) : [];
  const [more, setMore] = useState(false);
  return (
    <div className="rounded-xl border border-line bg-surface p-3 text-[12px] fade-in">
      <div className="mb-1.5 flex flex-wrap items-center gap-2">
        <span className="font-medium">Interpretation</span>
        <span className="rounded-full border border-line px-1.5 py-px text-[10px] uppercase tracking-wide text-muted">{spec.event_type.replace('_', ' ')}</span>
        <span className="text-[11px] text-muted">{spec.module ?? 'mock'} module · {spec.confidence} confidence · {spec.engine}{spec.parser ? ` · parsed by ${spec.parser}` : ''}</span>
      </div>
      <dl className="grid grid-cols-[72px_1fr] gap-x-2 gap-y-0.5">
        <dt className="text-muted">Origin</dt><dd>{spec.origin ? `${spec.origin.name}${spec.origin.country ? `, ${spec.origin.country}` : ''}` : 'global'}{spec.global && spec.origin ? ' (seeded globally)' : ''}</dd>
        <dt className="text-muted">Start</dt><dd className="num">{spec.start_date}</dd>
        <dt className="text-muted">Horizon</dt><dd className="num">{spec.horizon_days} days · {spec.step_days}-day steps</dd>
        <dt className="text-muted">Domains</dt><dd>{spec.domains.join(', ').replace(/_/g, ' ')}</dd>
        <dt className="text-muted">Actors</dt><dd>{spec.actors.join(', ')}</dd>
        <dt className="text-muted">Mechanisms</dt><dd>{spec.mechanisms.join(' → ')}</dd>
        {!!spec.interventions?.length && (<><dt className="text-muted">Changes</dt><dd>{spec.interventions.map((i) => `${i.kind.replace('_', ' ')} day ${i.day}${i.value != null ? ` (${i.value > 0 ? '+' : ''}${i.value})` : ''}`).join('; ')}</dd></>)}
      </dl>
      <div className="mt-2 flex flex-wrap gap-1">
        {spec.assumptions.map((a) => <Chip key={a.id} a={a} editable={isCurrent && !readOnly} />)}
        {more && extra.map((a) => <Chip key={a.id} a={a} editable={isCurrent && !readOnly} />)}
      </div>
      {extra.length > 0 && (
        <button className="mt-1 text-[11px] underline" onClick={() => setMore(!more)}>{more ? 'Hide model assumptions' : `Show ${extra.length} model assumptions (editable)`}</button>
      )}
      <p className="mt-2 text-[10px] text-muted">Hover a chip for origin, confidence, source and range. Click a numeric chip to edit it; the edit runs as a branch with the same seed.</p>
    </div>
  );
}

function SummaryCard({ summary }: { summary: Summary }) {
  const runId = useStore((s) => s.runId);
  const report = useStore((s) => s.report);
  const parent = useStore((s) => s.parentRunId);
  const setCompare = useStore((s) => s.setCompare);
  const [copied, setCopied] = useState(false);
  return (
    <div className="rounded-xl border border-ink p-3 text-[12px] fade-in">
      <div className="mb-1 text-[10px] uppercase tracking-wide text-muted">Summary · {report?.confidence.overall ?? 'mock'} confidence</div>
      <p className="font-medium leading-snug">{report?.headline ?? summary.headline}</p>
      <table className="mt-2 w-full text-[11px]">
        <thead><tr className="text-left text-[10px] text-muted"><th className="py-1 font-normal">Outcome</th><th className="py-1 text-right font-normal">Median</th><th className="py-1 text-right font-normal">90% interval</th></tr></thead>
        <tbody>
          {summary.metrics.map((m) => (
            <tr key={m.name} className="border-t border-line" title={m.low50 != null ? `50% interval ${fmtNum(m.low50)}–${fmtNum(m.high50)} ${m.unit}` : undefined}>
              <td className="py-1 pr-2 text-muted">{m.name} <span className="text-[10px]">({m.unit})</span></td>
              <td className="num py-1 text-right">{fmtNum(m.value, m.unit)}</td>
              <td className="num py-1 pl-2 text-right text-muted">{m.low != null ? `${fmtNum(m.low, m.unit)}–${fmtNum(m.high, m.unit)}` : 'single run'}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="mt-2 text-[10px] text-muted">{summary.note}</p>
      {runId && report && (
        <div className="mt-2 flex flex-wrap gap-1.5">
          <a className="rounded-full bg-ink px-3 py-1 text-[11px] text-bg" href={`/report/${runId}`} target="_blank" rel="noopener">Full report</a>
          <a className="rounded-full border border-line px-3 py-1 text-[11px] hover:bg-surface" href={`/api/runs/${runId}/report.md`}>Markdown</a>
          <button className="rounded-full border border-line px-3 py-1 text-[11px] hover:bg-surface" onClick={async () => { try { await navigator.clipboard.writeText(shareLink(runId)); setCopied(true); } catch {} }}>{copied ? 'Link copied' : 'Share link'}</button>
          {parent && <button className="rounded-full border border-line px-3 py-1 text-[11px] hover:bg-surface" onClick={() => setCompare({ a: parent, b: runId })}>Compare with baseline</button>}
        </div>
      )}
    </div>
  );
}

const ROLE_LABEL: Record<string, string> = { calibrator: 'Calibrator', actors: 'Actors', replan: 'Actors, re-plan', crowds: 'Crowds', critic: 'Critic' };

/** The AI roles that shaped the run being shown: status, what each changed, and cost. */
function AgentRoster({ runId }: { runId?: string }) {
  const current = useStore((s) => s.runId);
  const steps = useStore((s) => s.agents);
  if (!runId || runId !== current || !steps.length) return null;
  const usd = steps.reduce((t, a) => t + (a.usd ?? 0), 0);
  return (
    <div className="rounded-xl border border-line p-3 text-[12px] fade-in" aria-live="polite">
      <div className="mb-1 flex flex-wrap items-baseline gap-2">
        <span className="font-medium">Agents</span>
        <span className="text-[11px] text-muted">AI roles that shaped this run · <span className="num">${usd.toFixed(3)}</span></span>
      </div>
      <ul className="space-y-1">
        {steps.map((a) => (
          <li key={a.role} className="flex gap-2">
            {/* status by fill: solid = done, pulsing ring = working, hairline = failed or skipped */}
            <span aria-hidden className={`mt-1 inline-block h-2 w-2 shrink-0 rounded-full ${a.status === 'done' ? 'bg-ink' : a.status === 'running' ? 'animate-pulse border border-ink' : 'border border-line'}`} />
            <span className="min-w-0 flex-1">
              <span className="font-medium">{ROLE_LABEL[a.role] ?? a.role}</span> <span className="text-[10px] text-muted">{a.model.replace('claude-', '')} · {a.status}</span>
              <span className="block text-muted">{a.summary}</span>
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

/** Scale card for the run being shown: plausibility at once, the AI forecast when ready, the measurement with the report. */
function LiveScale({ spec, runId }: { spec: ScenarioSpec; runId?: string }) {
  const current = useStore((s) => s.runId);
  const live = useStore((s) => s.scale);
  const report = useStore((s) => s.report);
  if (!runId || runId !== current) return null;
  const plausibility = live?.plausibility ?? spec.plausibility ?? null;
  const hypothesis = live?.hypothesis ?? spec.scale ?? null;
  if (!plausibility && !hypothesis && !report?.scale) return null;
  return <ScaleCard plausibility={plausibility} hypothesis={hypothesis} scale={report?.scale} />;
}

function Message({ m }: { m: ChatMessage }) {
  if (m.role === 'user') return <div className="ml-8 self-end rounded-xl bg-ink px-3 py-1.5 text-[12px] text-bg">{m.text}</div>;
  if (m.kind === 'spec' && m.spec) return <><SpecCard spec={m.spec} runId={m.runId} /><AgentRoster runId={m.runId} /><LiveScale spec={m.spec} runId={m.runId} /></>;
  if (m.kind === 'list') return <ul className="list-disc space-y-0.5 pl-4 text-[12px]">{m.items?.map((it, i) => <li key={i}>{it}</li>)}</ul>;
  return <p className="whitespace-pre-wrap text-[12px]">{m.text}</p>;
}

function Moments({ moments, stepDays }: { moments: SimEvent[]; stepDays: number }) {
  return (
    <div className="text-[12px]">
      <div className="mb-1 text-[10px] uppercase tracking-wide text-muted">Notable moments</div>
      <ul className="space-y-0.5">
        {moments.slice(-14).map((e) => (
          <li key={e.id} className="flex gap-2" title={e.cause}>
            <span className="num shrink-0 text-muted">{e.date} <span className="hidden sm:inline">· d{e.t * stepDays}</span></span>
            <span className={e.severity === 3 ? 'font-medium' : ''}>{e.title}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function RunsTab() {
  const history = useStore((s) => s.history);
  const current = useStore((s) => s.runId);
  const setCompare = useStore((s) => s.setCompare);
  useEffect(() => { void refreshHistory(); }, []);
  const roots = history.filter((r) => !r.parent_run_id || !history.some((h) => h.run_id === r.parent_run_id));
  const children = (id: string) => history.filter((r) => r.parent_run_id === id);
  const Row = ({ r, depth }: { r: RunListItem; depth: number }) => (
    <>
      <li className={`flex items-center gap-2 px-3 py-1.5 ${r.run_id === current ? 'bg-surface' : ''}`} style={{ paddingLeft: 12 + depth * 14 }}>
        {depth > 0 && <span aria-hidden className="text-muted">↳</span>}
        <button className="min-w-0 flex-1 truncate text-left text-[12px] hover:underline" onClick={() => loadRun(r.run_id)} title={`${r.run_id} · seed ${r.seed}`}>
          {r.label ?? r.title}
        </button>
        <span className="text-[10px] text-muted">{r.module}</span>
        {r.parent_run_id && <button className="rounded-full border border-line px-2 text-[10px] hover:bg-surface" onClick={() => setCompare({ a: r.parent_run_id!, b: r.run_id })}>compare</button>}
      </li>
      {children(r.run_id).map((c) => <Row key={c.run_id} r={c} depth={depth + 1} />)}
    </>
  );
  return (
    <ul className="min-h-0 flex-1 divide-y divide-line overflow-y-auto">
      {roots.map((r) => <Row key={r.run_id} r={r} depth={0} />)}
      {!history.length && <li className="p-3 text-[12px] text-muted">No saved runs yet. Runs and their branches appear here.</li>}
    </ul>
  );
}

function LiveSuggestions() {
  const live = useStore((s) => s.live);
  useEffect(() => { void loadLive(); }, []);
  const items = live.flatMap((f) => f.items.slice(0, 3).map((i) => ({ ...i, feed: f })));
  if (!items.length) return null;
  return (
    <div className="mt-4">
      <div className="mb-1 text-[10px] uppercase tracking-wide text-muted">Live signals</div>
      <ul className="space-y-1">
        {items.slice(0, 5).map((i) => (
          <li key={`${i.feed.id}-${i.id}`} className="flex items-start gap-2">
            <button className="min-w-0 flex-1 text-left hover:underline" onClick={() => useStore.getState().setDraft(i.prompt)} title={`${i.feed.name} · ${i.feed.publisher} · ${i.feed.license} · retrieved ${i.feed.retrieved ?? 'never'}`}>
              {i.title}
            </button>
            <span className="shrink-0 text-[10px] text-muted">{i.feed.status === 'live' ? i.feed.publisher.split(' ').map((w) => w[0]).join('') : 'stale'}</span>
          </li>
        ))}
      </ul>
      <p className="mt-1 text-[10px] text-muted">Click a signal to draft a scenario from it. Rings on the map are USGS earthquakes from the past week.</p>
    </div>
  );
}

export default function ChatPanel() {
  const messages = useStore((s) => s.messages);
  const chatTab = useStore((s) => s.chatTab);
  const setChatTab = useStore((s) => s.setChatTab);
  const runStatus = useStore((s) => s.runStatus);
  const progress = useStore((s) => s.progress);
  const spec = useStore((s) => s.spec);
  const events = useStore((s) => s.events);
  const bubbles = useStore((s) => s.bubbles);
  const playhead = useStore((s) => s.playhead);
  const frames = useStore((s) => s.frames);
  const summary = useStore((s) => s.summary);
  const readOnly = useStore((s) => s.readOnly);
  const [input, setInput] = useState('');
  const listRef = useRef<HTMLDivElement>(null);
  const moments = events.filter((e) => e.t <= playhead);
  const atEnd = frames.length > 0 && playhead >= frames.length - 1 && runStatus === 'done';
  const busy = runStatus === 'parsing';
  const voiceCount = bubbles.filter((b) => b.t <= playhead).length;

  // drafts (from live signals or map clicks) arrive through the store; consume them in a subscription callback
  useEffect(() => useStore.subscribe(() => {
    const d = useStore.getState().draft;
    if (d) { setInput(d); useStore.getState().setChatTab('chat'); useStore.getState().setDraft(null); }
  }), []);
  useEffect(() => { listRef.current?.scrollTo({ top: listRef.current.scrollHeight }); }, [messages.length, atEnd, moments.length]);

  const tab = (on: boolean) => `rounded-full px-3 py-1 ${on ? 'bg-ink text-bg' : 'text-muted hover:bg-surface'}`;
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex h-10 shrink-0 items-center gap-1 border-b border-line px-2 text-[12px]" role="tablist">
        <button role="tab" aria-selected={chatTab === 'chat'} className={tab(chatTab === 'chat')} onClick={() => setChatTab('chat')}>Chat</button>
        <button role="tab" aria-selected={chatTab === 'voices'} className={tab(chatTab === 'voices')} onClick={() => setChatTab('voices')}>Voices <span className="num opacity-70">{voiceCount}</span></button>
        <button role="tab" aria-selected={chatTab === 'runs'} className={tab(chatTab === 'runs')} onClick={() => setChatTab('runs')}>Runs</button>
        {runStatus === 'streaming' && progress && (
          <div className="ml-auto flex items-center gap-2 text-[11px] text-muted"><span className="h-1 w-12 overflow-hidden rounded-full bg-surface"><span className="block h-full bg-ink" style={{ width: `${(progress.t / Math.max(progress.total, 1)) * 100}%` }} /></span><span className="num truncate">{progress.label}</span></div>
        )}
      </div>
      {chatTab === 'voices' ? <VoicesLog /> : chatTab === 'runs' ? <RunsTab /> : (
        <>
          <div ref={listRef} className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto px-3 py-3">
            {messages.length === 0 && !readOnly && (
              <div className="text-[12px] fade-in">
                <h1 className="text-[15px] font-medium">Simulate an event</h1>
                <p className="mt-1 text-muted">Type any real or hypothetical event. The simulated today is <span className="num">2026-10-20</span>. Every number traces to a dataset or a labeled assumption, and outcomes come with ranges.</p>
                <div className="mt-3 flex flex-col items-start gap-1.5">
                  {EXAMPLES.map((ex) => <button key={ex} className="rounded-full border border-line px-3 py-1 text-left hover:bg-surface" onClick={() => submitPrompt(ex)}>{ex}</button>)}
                </div>
                <LiveSuggestions />
              </div>
            )}
            {readOnly && <p className="rounded-xl border border-line p-2 text-[11px] text-muted">Read-only shared run. Replays the saved seed and configuration. <Link className="underline" href="/">Open Worldsim</Link> to run your own.</p>}
            {messages.map((m) => <Message key={m.id} m={m} />)}
            {spec && moments.length > 0 && <Moments moments={moments} stepDays={spec.step_days} />}
            {summary && atEnd && <SummaryCard summary={summary} />}
            {summary && !atEnd && runStatus === 'done' && (
              <div className="text-[11px] text-muted">Summary is ready at the end of the timeline. <button className="underline" onClick={() => { useStore.getState().setPlaying(false); useStore.getState().setPlayhead(frames.length - 1); }}>Skip to end</button></div>
            )}
          </div>
          <div className="sr-only" aria-live="polite">{progress?.label} {moments[moments.length - 1]?.title}</div>
          {!readOnly && (
            <form className="flex shrink-0 gap-2 border-t border-line p-2" onSubmit={(e) => { e.preventDefault(); const v = input; setInput(''); void submitPrompt(v); }}>
              <input className="min-w-0 flex-1 rounded-full border border-line bg-bg px-3 py-1.5 text-[13px] placeholder:text-muted" aria-label="Message" autoComplete="off" value={input} disabled={busy}
                placeholder={runStatus === 'awaiting_answer' ? 'Answer the question…' : spec ? 'Ask "what if…", "explain…", or describe a new event' : 'Describe an event…'} onChange={(e) => setInput(e.target.value)} />
              <button className="rounded-full bg-ink px-3 py-1.5 text-[12px] text-bg disabled:opacity-40" disabled={busy || !input.trim()}>Send</button>
            </form>
          )}
        </>
      )}
    </div>
  );
}
