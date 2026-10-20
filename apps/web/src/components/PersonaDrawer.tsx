'use client';
import { Fragment } from 'react';
import { useStore } from '@/lib/store';
import { STATUS_CODES, STATUS_INTENSITY, type PersonaStatus } from '@/lib/sim/types';

const W = 280, H = 48;

export default function PersonaDrawer() {
  const id = useStore((s) => s.selectedPersonaId);
  const personas = useStore((s) => s.personas);
  const personaIndex = useStore((s) => s.personaIndex);
  const statusAt = useStore((s) => s.statusAt);
  const frames = useStore((s) => s.frames);
  const bubbles = useStore((s) => s.bubbles);
  const spec = useStore((s) => s.spec);
  const playhead = useStore((s) => s.playhead);
  const selectPersona = useStore((s) => s.selectPersona);
  if (!id) return null;
  const i = personaIndex[id];
  const p = personas[i];
  if (!p) return null;

  const history: PersonaStatus[] = statusAt.map((arr) => STATUS_CODES[arr[i]]);
  const total = spec ? Math.ceil(spec.horizon_days / spec.step_days) + 1 : history.length;
  const x = (t: number) => (t / Math.max(total - 1, 1)) * W;
  const y = (s: PersonaStatus) => H - 2 - STATUS_INTENSITY[s] * (H - 4);
  let path = '';
  history.forEach((s, t) => { path += t === 0 ? `M${x(0)},${y(s)}` : ` L${x(t)},${y(history[t - 1])} L${x(t)},${y(s)}`; });
  const changes = history.flatMap((s, t) => (t === 0 ? s !== 'unaware' : s !== history[t - 1]) ? [{ t, s }] : []);
  const said = bubbles.filter((b) => b.persona_id === id && b.t <= playhead);
  const current = history[Math.min(playhead, history.length - 1)] ?? 'unaware';

  return (
    <aside className="fade-in absolute bottom-[93px] right-0 top-0 z-20 w-[320px] max-w-full md:bottom-[49px] overflow-y-auto border-l border-line bg-bg p-4 text-[12px]" aria-label="Persona details">
      <div className="flex items-start gap-2">
        <span aria-hidden className={`mt-1 inline-block h-3 w-3 shrink-0 bg-ink ${p.kind === 'people' ? 'rounded-full' : ''}`} />
        <div className="min-w-0 flex-1">
          <h2 className="text-[14px] font-medium leading-tight">{p.label}</h2>
          <div className="text-muted">{p.location.city}{p.location.admin1 ? `, ${p.location.admin1}` : ''} · {p.location.country_iso3}</div>
        </div>
        <button aria-label="Close" className="rounded-full border border-line px-2 py-0.5 hover:bg-surface" onClick={() => selectPersona(null)}>✕</button>
      </div>
      <dl className="mt-3 grid grid-cols-[88px_1fr] gap-x-2 gap-y-0.5">
        <dt className="text-muted">Represents</dt><dd className="num">{p.population_represented.toLocaleString()} people</dd>
        <dt className="text-muted">Status now</dt><dd>{current}</dd>
        {Object.entries(p.demographics).filter(([, v]) => v !== 'n/a').map(([k, v]) => <Fragment key={k}><dt className="text-muted">{k.replace('_', ' ')}</dt><dd>{v}</dd></Fragment>)}
      </dl>
      <h3 className="mb-1 mt-4 text-[10px] uppercase tracking-wide text-muted">Traits</h3>
      {Object.entries(p.traits).map(([k, v]) => (
        <div key={k} className="mb-1 flex items-center gap-2">
          <span className="w-[120px] shrink-0 text-muted">{k.replace('_', ' ')}</span>
          <div className="h-1.5 flex-1 bg-surface" role="meter" aria-valuenow={v} aria-valuemin={0} aria-valuemax={1} aria-label={k}><div className="h-full bg-ink" style={{ width: `${v * 100}%` }} /></div>
          <span className="num w-8 text-right">{v.toFixed(2)}</span>
        </div>
      ))}
      <h3 className="mb-1 mt-4 text-[10px] uppercase tracking-wide text-muted">State history</h3>
      <svg viewBox={`0 0 ${W} ${H}`} className="block h-12 w-full" role="img" aria-label={`Status intensity over ${history.length} steps`}>
        <line x1={0} y1={H - 2} x2={W} y2={H - 2} stroke="var(--line)" />
        {path && <path d={path} fill="none" stroke="currentColor" strokeWidth={1.5} />}
        <line x1={x(Math.min(playhead, total - 1))} y1={0} x2={x(Math.min(playhead, total - 1))} y2={H} stroke="currentColor" strokeDasharray="2 2" />
      </svg>
      <h3 className="mb-1 mt-4 text-[10px] uppercase tracking-wide text-muted">Memory</h3>
      <ul className="space-y-0.5">
        {changes.length === 0 && <li className="text-muted">Nothing yet.</li>}
        {changes.map((c) => <li key={c.t} className={`flex gap-2 ${c.t > playhead ? 'opacity-40' : ''}`}><span className="num text-muted">{frames[c.t]?.date}</span><span>{c.s}</span></li>)}
      </ul>
      <h3 className="mb-1 mt-4 text-[10px] uppercase tracking-wide text-muted">Said</h3>
      <ul className="space-y-1">
        {said.length === 0 && <li className="text-muted">Nothing yet.</li>}
        {said.map((b) => <li key={b.id} className="rounded-lg border border-line p-2"><div>{b.text}</div><div className="mt-0.5 text-[10px] text-muted">{frames[b.t]?.date} · {b.why.event} · {b.why.metric.replace('_', ' ')} <span className="num">{b.why.before} → {b.why.after}</span> {b.why.unit}</div></li>)}
      </ul>
      <p className="mt-4 text-[10px] text-muted">Voice: {p.voice}. {p.context.local_conditions.join(' · ')}.</p>
    </aside>
  );
}
