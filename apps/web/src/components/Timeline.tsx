'use client';
import { useStore, type Speed } from '@/lib/store';

export default function Timeline() {
  const spec = useStore((s) => s.spec);
  const frames = useStore((s) => s.frames);
  const events = useStore((s) => s.events);
  const playhead = useStore((s) => s.playhead);
  const playing = useStore((s) => s.playing);
  const speed = useStore((s) => s.speed);
  const progress = useStore((s) => s.progress);
  const { setPlayhead, setPlaying, setSpeed, step } = useStore.getState();
  const total = spec ? Math.ceil(spec.horizon_days / spec.step_days) : 0;
  const frame = frames[playhead];
  const icon = 'flex h-7 w-7 items-center justify-center rounded-full border border-line hover:bg-surface disabled:opacity-40';

  return (
    <div className="absolute inset-x-0 bottom-11 z-10 border-t border-line bg-bg/95 px-3 py-2 backdrop-blur md:bottom-0">
      <div className="flex items-center gap-2">
        <button className={icon} aria-label={playing ? 'Pause' : 'Play'} onClick={() => setPlaying(!playing)} disabled={!frames.length}>
          {playing ? <svg width="10" height="10" viewBox="0 0 10 10" aria-hidden><rect x="1" y="1" width="3" height="8" fill="currentColor" /><rect x="6" y="1" width="3" height="8" fill="currentColor" /></svg>
            : <svg width="10" height="10" viewBox="0 0 10 10" aria-hidden><path d="M2 1l7 4-7 4z" fill="currentColor" /></svg>}
        </button>
        <button className={icon} aria-label="Step back" onClick={() => step(-1)} disabled={!frames.length}>‹</button>
        <button className={icon} aria-label="Step forward" onClick={() => step(1)} disabled={!frames.length}>›</button>
        <div className="flex overflow-hidden rounded-full border border-line text-[11px]" role="group" aria-label="Playback speed">
          {([1, 4, 16] as Speed[]).map((s) => (
            <button key={s} className={`num px-2 py-0.5 ${speed === s ? 'bg-ink text-bg' : 'hover:bg-surface'}`} aria-pressed={speed === s} onClick={() => setSpeed(s)}>{s}×</button>
          ))}
        </div>
        <span className="num hidden min-w-[150px] text-[11px] text-muted sm:block">{frame ? `${frame.date} · day ${frame.t * (spec?.step_days ?? 1)}` : spec ? 'Waiting for frames…' : 'No scenario'}</span>
        <div className="relative flex-1">
          <input type="range" min={0} max={Math.max(total, 1)} value={playhead} step={1} disabled={!frames.length} aria-label="Timeline" aria-valuetext={frame?.date}
            onChange={(e) => { setPlaying(false); setPlayhead(+e.target.value); }} />
          <div className="pointer-events-none absolute inset-x-0 top-1/2 h-0">
            {events.map((e) => (
              <span key={e.id} className={`absolute -translate-x-1/2 -translate-y-1/2 ${e.severity === 3 ? 'h-3 w-[2px] bg-ink' : 'h-2 w-[2px] bg-muted'}`} style={{ left: `${(e.t / Math.max(total, 1)) * 100}%` }} title={`${e.date}: ${e.title}`} />
            ))}
          </div>
        </div>
        <span className="num hidden text-[11px] text-muted md:block">{progress?.label ?? ''}</span>
      </div>
    </div>
  );
}
