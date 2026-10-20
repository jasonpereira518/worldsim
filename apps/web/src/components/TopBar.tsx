'use client';
import { useStore } from '@/lib/store';
import { stopRun, submitPrompt } from '@/lib/runClient';

export default function TopBar() {
  const spec = useStore((s) => s.spec);
  const frames = useStore((s) => s.frames);
  const playhead = useStore((s) => s.playhead);
  const runStatus = useStore((s) => s.runStatus);
  const theme = useStore((s) => s.theme);
  const setTheme = useStore((s) => s.setTheme);
  const dataOpen = useStore((s) => s.dataDrawerOpen);
  const setDataOpen = useStore((s) => s.setDataDrawerOpen);
  const date = frames[playhead]?.date ?? spec?.start_date ?? '2026-10-20';
  const btn = 'rounded-full border border-line px-2.5 py-1 text-[12px] hover:bg-surface disabled:opacity-40 disabled:hover:bg-transparent';

  return (
    <header className="flex h-12 shrink-0 items-center gap-3 border-b border-line px-3">
      <div className="flex items-center gap-2 text-[14px] font-semibold tracking-tight"><span aria-hidden className="inline-block h-3 w-3 bg-ink" />Worldsim</div>
      <span className="hidden whitespace-nowrap rounded-full border border-line px-2 py-0.5 text-[10px] uppercase tracking-wide text-muted sm:inline" title="Milestone 0: deterministic mock diffusion engine, not a calibrated model">Mock engine · M0</span>
      <div className="min-w-0 flex-1 truncate text-muted" title={spec?.title}>{spec?.title ?? 'Describe an event in the chat to start a simulation'}</div>
      <time className="num hidden text-[12px] sm:block" dateTime={date} title="Simulated date">{date}</time>
      <div className="flex items-center gap-1.5">
        <button className={btn} disabled={runStatus !== 'streaming'} onClick={stopRun} title="Stop early and keep what was simulated">Stop</button>
        <button className={btn} disabled={!spec} onClick={() => spec && submitPrompt(spec.prompt)} title="Restart this scenario">Restart</button>
        <button className={btn} onClick={() => setDataOpen(!dataOpen)} aria-pressed={dataOpen} title="Data sources, freshness and assumptions (/sources)">Data</button>
        <button className={btn} disabled title="Export (PDF/Markdown) arrives in Milestone 4">Export</button>
        <button className={btn} onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')} aria-pressed={theme === 'dark'} title="Toggle dark mode">{theme === 'dark' ? 'Light' : 'Dark'}</button>
      </div>
    </header>
  );
}
