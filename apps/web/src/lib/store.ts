import { createStore } from './createStore';
import type { Bubble, Frame, Persona, ScenarioSpec, ServerEvent, SimEvent, Summary, Theme } from './sim/types';
import { STATUS_CODES } from './sim/types';

export type RunStatus = 'idle' | 'parsing' | 'awaiting_answer' | 'streaming' | 'done' | 'error';
export type Speed = 1 | 4 | 16;
export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  kind: 'text' | 'spec' | 'summary' | 'list';
  text?: string;
  spec?: ScenarioSpec;
  summary?: Summary;
  items?: string[];
}
export interface Layers { dots: boolean; institutions: boolean; flows: boolean; bubbles: boolean }
export interface Filters { country: string; kind: 'all' | 'people' | 'institution'; sentiment: 'all' | '-1' | '0' | '1' }

export interface WorldsimState {
  runId: string | null;
  spec: ScenarioSpec | null;
  runStatus: RunStatus;
  progress: { t: number; total: number; label: string } | null;
  personas: Persona[];
  personaIndex: Record<string, number>;
  frames: Frame[];
  /** statusAt[t][personaIndex] = STATUS_CODES index; built incrementally so scrubbing is O(1) */
  statusAt: Uint8Array[];
  events: SimEvent[];
  bubbles: Bubble[];
  summary: Summary | null;
  playhead: number;
  playing: boolean;
  speed: Speed;
  theme: Theme;
  layers: Layers;
  filters: Filters;
  selectedPersonaId: string | null;
  chatTab: 'chat' | 'voices';
  sheetOpen: boolean;
  messages: ChatMessage[];
  pendingPrompt: string | null;
  zoomRequest: { center: [number, number]; zoom: number; nonce: number } | null;

  reset(): void;
  setTheme(t: Theme): void;
  toggleLayer(k: keyof Layers): void;
  setFilters(f: Partial<Filters>): void;
  selectPersona(id: string | null): void;
  setPlayhead(t: number): void;
  setPlaying(p: boolean): void;
  setSpeed(s: Speed): void;
  step(d: number): void;
  setChatTab(tab: 'chat' | 'voices'): void;
  setSheetOpen(open: boolean): void;
  addMessage(m: Omit<ChatMessage, 'id'>): void;
  setRunStatus(s: RunStatus): void;
  beginRun(runId: string, spec: ScenarioSpec): void;
  setPendingPrompt(p: string | null): void;
  applyServerEvent(ev: ServerEvent): void;
  requestZoom(center: [number, number], zoom: number): void;
}

let msgSeq = 0;
const initialRun = {
  runId: null, spec: null, runStatus: 'idle' as RunStatus, progress: null, personas: [], personaIndex: {}, frames: [], statusAt: [],
  events: [], bubbles: [], summary: null, playhead: 0, playing: false, selectedPersonaId: null, pendingPrompt: null, zoomRequest: null,
};

export const useStore = createStore<WorldsimState>((set, get) => ({
  ...initialRun,
  speed: 1,
  theme: 'light',
  layers: { dots: true, institutions: true, flows: true, bubbles: true },
  filters: { country: 'all', kind: 'all', sentiment: 'all' },
  chatTab: 'chat',
  sheetOpen: false,
  messages: [],

  reset: () => set({ ...initialRun, messages: [], chatTab: 'chat' }),
  setTheme: (theme) => {
    try { localStorage.setItem('worldsim-theme', theme); } catch {}
    document.documentElement.setAttribute('data-theme', theme);
    set({ theme });
  },
  toggleLayer: (k) => set((s) => ({ layers: { ...s.layers, [k]: !s.layers[k] } })),
  setFilters: (f) => set((s) => ({ filters: { ...s.filters, ...f } })),
  selectPersona: (id) => set({ selectedPersonaId: id }),
  setPlayhead: (t) => set((s) => ({ playhead: Math.max(0, Math.min(t, s.frames.length - 1)) })),
  setPlaying: (playing) => set({ playing }),
  setSpeed: (speed) => set({ speed }),
  step: (d) => set((s) => ({ playhead: Math.max(0, Math.min(s.playhead + d, s.frames.length - 1)), playing: false })),
  setChatTab: (chatTab) => set({ chatTab }),
  setSheetOpen: (sheetOpen) => set({ sheetOpen }),
  addMessage: (m) => set((s) => ({ messages: [...s.messages, { ...m, id: `m${++msgSeq}` }] })),
  setRunStatus: (runStatus) => set({ runStatus }),
  setPendingPrompt: (pendingPrompt) => set({ pendingPrompt }),
  beginRun: (runId, spec) => set({ ...initialRun, runId, spec, runStatus: 'streaming', playing: true }),
  requestZoom: (center, zoom) => set({ zoomRequest: { center, zoom, nonce: Date.now() } }),

  applyServerEvent: (ev) => {
    const s = get();
    switch (ev.type) {
      case 'personas': {
        const personaIndex: Record<string, number> = {};
        ev.personas.forEach((p, i) => { personaIndex[p.id] = i; });
        set({ personas: ev.personas, personaIndex, frames: [], statusAt: [], events: [], bubbles: [], playhead: 0 });
        return;
      }
      case 'frame': {
        const f = ev.frame;
        const prev = s.statusAt[s.statusAt.length - 1];
        const next = prev ? new Uint8Array(prev) : new Uint8Array(s.personas.length);
        for (const d of f.deltas) {
          const i = s.personaIndex[d.id];
          if (i !== undefined) next[i] = STATUS_CODES.indexOf(d.status);
        }
        set({
          frames: [...s.frames, f],
          statusAt: [...s.statusAt, next],
          events: f.events.length ? [...s.events, ...f.events] : s.events,
          bubbles: f.bubbles.length ? [...s.bubbles, ...f.bubbles] : s.bubbles,
        });
        return;
      }
      case 'progress': set({ progress: { t: ev.t, total: ev.total, label: ev.label } }); return;
      case 'summary': set({ summary: ev.summary }); return;
      case 'done': set({ runStatus: 'done', progress: s.progress ? { ...s.progress, label: 'Simulation complete' } : null }); return;
      case 'error': set({ runStatus: 'error' }); get().addMessage({ role: 'assistant', kind: 'text', text: `Engine error: ${ev.message}` }); return;
    }
  },
}));

/** Status name for persona index i at step t (defaults to 'unaware'). */
export const statusOf = (statusAt: Uint8Array[], t: number, i: number) => STATUS_CODES[statusAt[Math.min(t, statusAt.length - 1)]?.[i] ?? 0];
