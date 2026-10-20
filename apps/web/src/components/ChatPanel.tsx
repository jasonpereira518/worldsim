'use client';
import { useEffect, useRef, useState } from 'react';
import { useStore, type ChatMessage } from '@/lib/store';
import { EXAMPLES, submitPrompt } from '@/lib/runClient';
import type { ScenarioSpec, SimEvent, Summary } from '@/lib/sim/types';
import VoicesLog from './VoicesLog';

export const fmtNum = (v: number, unit: string) => (unit === 'people' ? (v >= 1e9 ? `${(v / 1e9).toFixed(2)}B` : v >= 1e6 ? `${(v / 1e6).toFixed(1)}M` : v >= 1e3 ? `${Math.round(v / 1e3)}k` : String(Math.round(v))) : v.toLocaleString(undefined, { maximumFractionDigits: 2 }));

function SpecCard({ spec }: { spec: ScenarioSpec }) {
  return (
    <div className="rounded-xl border border-line bg-surface p-3 text-[12px] fade-in">
      <div className="mb-1.5 flex flex-wrap items-center gap-2">
        <span className="font-medium">Interpretation</span>
        <span className="rounded-full border border-line px-1.5 py-px text-[10px] uppercase tracking-wide text-muted">{spec.event_type.replace('_', ' ')}</span>
        <span className="text-[11px] text-muted">{spec.confidence} confidence · {spec.engine}</span>
      </div>
      <dl className="grid grid-cols-[72px_1fr] gap-x-2 gap-y-0.5">
        <dt className="text-muted">Origin</dt><dd>{spec.origin ? `${spec.origin.name}, ${spec.origin.country}` : 'global'}{spec.global && spec.origin ? ' (seeded globally)' : ''}</dd>
        <dt className="text-muted">Start</dt><dd className="num">{spec.start_date}</dd>
        <dt className="text-muted">Horizon</dt><dd className="num">{spec.horizon_days} days · {spec.step_days}-day steps</dd>
        <dt className="text-muted">Domains</dt><dd>{spec.domains.join(', ').replace(/_/g, ' ')}</dd>
        <dt className="text-muted">Actors</dt><dd>{spec.actors.join(', ')}</dd>
        <dt className="text-muted">Mechanisms</dt><dd>{spec.mechanisms.join(' → ')}</dd>
      </dl>
      <div className="mt-2 flex flex-wrap gap-1">
        {spec.assumptions.map((a) => (
          <span key={a.id} className="rounded-full border border-line bg-bg px-2 py-0.5 text-[11px]" title={`origin: ${a.origin} · ${a.confidence} confidence`}>{a.text}</span>
        ))}
      </div>
      <p className="mt-2 text-[10px] text-muted">Hover a chip for its origin and confidence. Editing assumptions arrives in Milestone 2.</p>
    </div>
  );
}

function SummaryCard({ summary }: { summary: Summary }) {
  return (
    <div className="rounded-xl border border-ink p-3 text-[12px] fade-in">
      <div className="mb-1 text-[10px] uppercase tracking-wide text-muted">Summary · mock engine</div>
      <p className="font-medium leading-snug">{summary.headline}</p>
      <table className="mt-2 w-full text-[11px]">
        <tbody>
          {summary.metrics.map((m) => (
            <tr key={m.name} className="border-t border-line">
              <td className="py-1 pr-2 text-muted">{m.name}</td>
              <td className="num py-1 text-right">{fmtNum(m.value, m.unit)}</td>
              <td className="py-1 pl-2 text-muted">{m.unit}</td>
              <td className="py-1 pl-2 text-right text-muted">{m.confidence}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="mt-2 text-[10px] text-muted">{summary.note} The full report (timeline, winners and losers, causal chain, sensitivities, sources) arrives in Milestone 2.</p>
    </div>
  );
}

function Message({ m }: { m: ChatMessage }) {
  if (m.role === 'user') return <div className="ml-8 self-end rounded-xl bg-ink px-3 py-1.5 text-[12px] text-bg">{m.text}</div>;
  if (m.kind === 'spec' && m.spec) return <SpecCard spec={m.spec} />;
  if (m.kind === 'list') return <ul className="list-disc space-y-0.5 pl-4 text-[12px]">{m.items?.map((it, i) => <li key={i}>{it}</li>)}</ul>;
  return <p className="whitespace-pre-wrap text-[12px]">{m.text}</p>;
}

function Moments({ moments, stepDays }: { moments: SimEvent[]; stepDays: number }) {
  return (
    <div className="text-[12px]">
      <div className="mb-1 text-[10px] uppercase tracking-wide text-muted">Notable moments</div>
      <ul className="space-y-0.5">
        {moments.map((e) => (
          <li key={e.id} className="flex gap-2" title={e.cause}>
            <span className="num shrink-0 text-muted">{e.date} <span className="hidden sm:inline">· d{e.t * stepDays}</span></span>
            <span className={e.severity === 3 ? 'font-medium' : ''}>{e.title}</span>
          </li>
        ))}
      </ul>
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
  const [input, setInput] = useState('');
  const listRef = useRef<HTMLDivElement>(null);
  const moments = events.filter((e) => e.t <= playhead);
  const atEnd = frames.length > 0 && playhead >= frames.length - 1 && runStatus === 'done';
  const busy = runStatus === 'parsing';
  const voiceCount = bubbles.filter((b) => b.t <= playhead).length;

  useEffect(() => { listRef.current?.scrollTo({ top: listRef.current.scrollHeight }); }, [messages.length, atEnd, moments.length]);

  const tab = (on: boolean) => `rounded-full px-3 py-1 ${on ? 'bg-ink text-bg' : 'text-muted hover:bg-surface'}`;
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex h-10 shrink-0 items-center gap-1 border-b border-line px-2 text-[12px]" role="tablist">
        <button role="tab" aria-selected={chatTab === 'chat'} className={tab(chatTab === 'chat')} onClick={() => setChatTab('chat')}>Chat</button>
        <button role="tab" aria-selected={chatTab === 'voices'} className={tab(chatTab === 'voices')} onClick={() => setChatTab('voices')}>Voices <span className="num opacity-70">{voiceCount}</span></button>
        {runStatus === 'streaming' && progress && (
          <div className="ml-auto flex items-center gap-2 text-[11px] text-muted"><span className="h-1 w-16 overflow-hidden rounded-full bg-surface"><span className="block h-full bg-ink" style={{ width: `${(progress.t / progress.total) * 100}%` }} /></span><span className="num">{progress.label}</span></div>
        )}
      </div>
      {chatTab === 'voices' ? <VoicesLog /> : (
        <>
          <div ref={listRef} className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto px-3 py-3">
            {messages.length === 0 && (
              <div className="text-[12px] fade-in">
                <h1 className="text-[15px] font-medium">Simulate an event</h1>
                <p className="mt-1 text-muted">Type any real or hypothetical event. The simulated today is <span className="num">2026-10-20</span>. This build runs a mock engine; every number is labeled as such.</p>
                <div className="mt-3 flex flex-col items-start gap-1.5">
                  {EXAMPLES.map((ex) => <button key={ex} className="rounded-full border border-line px-3 py-1 text-left hover:bg-surface" onClick={() => submitPrompt(ex)}>{ex}</button>)}
                </div>
              </div>
            )}
            {messages.map((m) => <Message key={m.id} m={m} />)}
            {spec && moments.length > 0 && <Moments moments={moments} stepDays={spec.step_days} />}
            {summary && atEnd && <SummaryCard summary={summary} />}
            {summary && !atEnd && runStatus === 'done' && (
              <div className="text-[11px] text-muted">Summary is ready at the end of the timeline. <button className="underline" onClick={() => { useStore.getState().setPlaying(false); useStore.getState().setPlayhead(frames.length - 1); }}>Skip to end</button></div>
            )}
          </div>
          <div className="sr-only" aria-live="polite">{progress?.label} {moments[moments.length - 1]?.title}</div>
          <form className="flex shrink-0 gap-2 border-t border-line p-2" onSubmit={(e) => { e.preventDefault(); const v = input; setInput(''); void submitPrompt(v); }}>
            <input className="min-w-0 flex-1 rounded-full border border-line bg-bg px-3 py-1.5 text-[13px] placeholder:text-muted" aria-label="Message" autoComplete="off" value={input} disabled={busy}
              placeholder={runStatus === 'awaiting_answer' ? 'Answer the question…' : spec ? 'Ask a follow-up or describe a new event…' : 'Describe an event…'} onChange={(e) => setInput(e.target.value)} />
            <button className="rounded-full bg-ink px-3 py-1.5 text-[12px] text-bg disabled:opacity-40" disabled={busy || !input.trim()}>Send</button>
          </form>
        </>
      )}
    </div>
  );
}
