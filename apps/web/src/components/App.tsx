'use client';
import { useEffect } from 'react';
import { useStore } from '@/lib/store';
import TopBar from './TopBar';
import MapView from './MapView';
import Timeline from './Timeline';
import LayerPills from './LayerPills';
import ChatPanel from './ChatPanel';
import PersonaDrawer from './PersonaDrawer';
import DataDrawer from './DataDrawer';
import CompareView from './CompareView';
import { loadLive, loadRun, refreshHistory } from '@/lib/runClient';

/** Client-side playback clock: 1× = 2 simulation steps per second. */
function usePlayback() {
  useEffect(() => {
    let raf = 0, last = performance.now(), acc = 0;
    const loop = (now: number) => {
      raf = requestAnimationFrame(loop);
      const s = useStore.getState();
      const dt = now - last; last = now;
      if (!s.playing) { acc = 0; return; }
      acc += (dt / 1000) * s.speed * 2;
      const n = Math.floor(acc);
      if (!n) return;
      acc -= n;
      const maxT = s.frames.length - 1;
      if (s.playhead < maxT) useStore.setState({ playhead: Math.min(maxT, s.playhead + n) });
      else if (s.runStatus !== 'streaming') useStore.setState({ playing: false });
    };
    raf = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(raf);
  }, []);
}

function useKeyboard() {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement;
      const s = useStore.getState();
      if (e.key === 'Escape') { s.selectPersona(null); s.setDataDrawerOpen(false); s.setCompare(null); return; } // closes drawers and the comparison from anywhere
      if (/^(INPUT|TEXTAREA|SELECT|BUTTON)$/.test(t.tagName) || t.isContentEditable || t.classList?.contains('maplibregl-canvas')) return;
      if (e.code === 'Space') { e.preventDefault(); s.setPlaying(!s.playing); }
      else if (e.key === 'ArrowRight') s.step(1);
      else if (e.key === 'ArrowLeft') s.step(-1);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);
}

export default function App({ initialRunId, readOnly = false }: { initialRunId?: string; readOnly?: boolean }) {
  usePlayback();
  useKeyboard();
  useEffect(() => {
    useStore.getState().setReadOnly(readOnly);
    const run = initialRunId ?? new URLSearchParams(location.search).get('run');
    // StrictMode mounts twice in development: load a shared or saved run only once
    if (run && !useStore.getState().runId) void loadRun(run);
    void refreshHistory();
    void loadLive();
    const id = setInterval(loadLive, 10 * 60 * 1000);
    return () => clearInterval(id);
  }, [initialRunId, readOnly]);
  const sheetOpen = useStore((s) => s.sheetOpen);
  const setSheetOpen = useStore((s) => s.setSheetOpen);
  useEffect(() => { useStore.setState({ theme: document.documentElement.getAttribute('data-theme') === 'dark' ? 'dark' : 'light' }); }, []);

  return (
    <div className="flex h-full flex-col">
      <TopBar />
      <div className="relative flex min-h-0 flex-1">
        <section className="relative min-w-0 flex-1">
          <MapView />
          <LayerPills />
          <PersonaDrawer />
          <DataDrawer />
          <CompareView />
          <Timeline />
        </section>
        <aside aria-label="Chat" className={`absolute inset-x-0 bottom-0 z-30 flex flex-col border-t border-line bg-bg transition-[height] duration-200 md:static md:h-auto md:w-[30%] md:min-w-[320px] md:max-w-[460px] md:border-l md:border-t-0 ${sheetOpen ? 'h-[55%]' : 'h-11'}`}>
          <button className="flex h-11 w-full shrink-0 items-center justify-center gap-2 text-[12px] text-muted md:hidden" onClick={() => setSheetOpen(!sheetOpen)} aria-expanded={sheetOpen}>
            <span aria-hidden className="h-1 w-8 rounded-full bg-line" />{sheetOpen ? 'Hide chat' : 'Chat'}
          </button>
          <div className={`${sheetOpen ? 'flex' : 'hidden'} min-h-0 flex-1 flex-col md:flex`}><ChatPanel /></div>
        </aside>
      </div>
    </div>
  );
}
