import { createStore } from './createStore';
import type { Bubble, Frame, Persona, Report, RunListItem, RunMeta, ScenarioSpec, ServerEvent, SimEvent, Summary, Theme } from './sim/types';
import { STATUS_CODES } from './sim/types';

export type RunStatus = 'idle' | 'parsing' | 'awaiting_answer' | 'streaming' | 'done' | 'error';
export type Speed = 1 | 4 | 16;
export type ChatTab = 'chat' | 'voices' | 'runs';
export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  kind: 'text' | 'spec' | 'summary' | 'list';
  text?: string;
  spec?: ScenarioSpec;
  runId?: string;
  summary?: Summary;
  items?: string[];
}
export interface Layers { dots: boolean; institutions: boolean; flows: boolean; bubbles: boolean; live: boolean }
export interface Filters { country: string; kind: 'all' | 'people' | 'institution'; sentiment: 'all' | '-1' | '0' | '1' }
export interface LiveItem { id: string; title: string; time: string; lat?: number; lon?: number; magnitude?: number; url?: string | null; prompt: string }
export interface LiveFeed { id: string; name: string; publisher: string; license: string; retrieved: string | null; status: 'live' | 'stale' | 'unavailable'; error: string | null; items: LiveItem[] }

export interface WorldsimState {
  runId: string | null;
  parentRunId: string | null;
  spec: ScenarioSpec | null;
  meta: RunMeta | null;
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
  report: Report | null;
  playhead: number;
  playing: boolean;
  speed: Speed;
  theme: Theme;
  layers: Layers;
  /** key of the choropleth layer shown on the map, or null */
  choropleth: string | null;
  filters: Filters;
  selectedPersonaId: string | null;
  dataDrawerOpen: boolean;
  chatTab: ChatTab;
  sheetOpen: boolean;
  messages: ChatMessage[];
  pendingPrompt: string | null;
  zoomRequest: { center: [number, number]; zoom: number; nonce: number } | null;
  history: RunListItem[];
  compare: { a: string; b: string } | null;
  live: LiveFeed[];
  readOnly: boolean;
  /** text to place in the chat input (e.g. from a live-feed item) */
  draft: string | null;

  reset(): void;
  setTheme(t: Theme): void;
  toggleLayer(k: keyof Layers): void;
  setLayers(l: Partial<Layers>): void;
  setChoropleth(key: string | null): void;
  setFilters(f: Partial<Filters>): void;
  selectPersona(id: string | null): void;
  setDataDrawerOpen(open: boolean): void;
  setPlayhead(t: number): void;
  setPlaying(p: boolean): void;
  setSpeed(s: Speed): void;
  step(d: number): void;
  setChatTab(tab: ChatTab): void;
  setSheetOpen(open: boolean): void;
  addMessage(m: Omit<ChatMessage, 'id'>): void;
  setRunStatus(s: RunStatus): void;
  beginRun(runId: string, spec: ScenarioSpec, parentRunId?: string | null): void;
  setPendingPrompt(p: string | null): void;
  applyServerEvent(ev: ServerEvent): void;
  requestZoom(center: [number, number], zoom: number): void;
  setHistory(h: RunListItem[]): void;
  setCompare(c: { a: string; b: string } | null): void;
  setLive(l: LiveFeed[]): void;
  setReadOnly(r: boolean): void;
  setDraft(d: string | null): void;
}

let msgSeq = 0;
const initialRun = {
  runId: null, parentRunId: null, spec: null, meta: null, runStatus: 'idle' as RunStatus, progress: null, personas: [], personaIndex: {}, frames: [],
  statusAt: [], events: [], bubbles: [], summary: null, report: null, playhead: 0, playing: false, selectedPersonaId: null, pendingPrompt: null,
  zoomRequest: null,
};

export const useStore = createStore<WorldsimState>((set, get) => ({
  ...initialRun,
  speed: 1,
  theme: 'light',
  layers: { dots: true, institutions: true, flows: true, bubbles: true, live: true },
  choropleth: null,
  filters: { country: 'all', kind: 'all', sentiment: 'all' },
  dataDrawerOpen: false,
  chatTab: 'chat',
  sheetOpen: false,
  messages: [],
  history: [],
  compare: null,
  live: [],
  readOnly: false,
  draft: null,

  reset: () => set({ ...initialRun, messages: [], chatTab: 'chat', compare: null }),
  setTheme: (theme) => {
    try { localStorage.setItem('worldsim-theme', theme); } catch {}
    document.documentElement.setAttribute('data-theme', theme);
    set({ theme });
  },
  toggleLayer: (k) => set((s) => ({ layers: { ...s.layers, [k]: !s.layers[k] } })),
  setLayers: (l) => set((s) => ({ layers: { ...s.layers, ...l } })),
  setChoropleth: (choropleth) => set({ choropleth }),
  setFilters: (f) => set((s) => ({ filters: { ...s.filters, ...f } })),
  // the persona drawer and the data drawer share the right edge of the map: opening one closes the other
  selectPersona: (id) => set(id ? { selectedPersonaId: id, dataDrawerOpen: false } : { selectedPersonaId: null }),
  setDataDrawerOpen: (open) => set(open ? { dataDrawerOpen: true, selectedPersonaId: null } : { dataDrawerOpen: false }),
  setPlayhead: (t) => set((s) => ({ playhead: Math.max(0, Math.min(t, s.frames.length - 1)) })),
  setPlaying: (playing) => set({ playing }),
  setSpeed: (speed) => set({ speed }),
  step: (d) => set((s) => ({ playhead: Math.max(0, Math.min(s.playhead + d, s.frames.length - 1)), playing: false })),
  setChatTab: (chatTab) => set({ chatTab }),
  setSheetOpen: (sheetOpen) => set({ sheetOpen }),
  addMessage: (m) => set((s) => ({ messages: [...s.messages, { ...m, id: `m${++msgSeq}` }] })),
  setRunStatus: (runStatus) => set({ runStatus }),
  setPendingPrompt: (pendingPrompt) => set({ pendingPrompt }),
  beginRun: (runId, spec, parentRunId = null) => set({ ...initialRun, runId, spec, parentRunId, runStatus: 'streaming', playing: true }),
  requestZoom: (center, zoom) => set({ zoomRequest: { center, zoom, nonce: Date.now() } }),
  setHistory: (history) => set({ history }),
  setCompare: (compare) => set({ compare }),
  setLive: (live) => set({ live }),
  setReadOnly: (readOnly) => set({ readOnly }),
  setDraft: (draft) => set({ draft }),

  applyServerEvent: (ev) => {
    const s = get();
    switch (ev.type) {
      case 'personas': {
        const personaIndex: Record<string, number> = {};
        ev.personas.forEach((p, i) => { personaIndex[p.id] = i; });
        set({ personas: ev.personas, personaIndex, frames: [], statusAt: [], events: [], bubbles: [], playhead: 0 });
        return;
      }
      case 'meta': {
        // keep the chosen choropleth when the new module has the same layer, otherwise show its first layer
        const keep = ev.meta.layers.some((l) => l.key === s.choropleth);
        set({ meta: ev.meta, choropleth: keep ? s.choropleth : ev.meta.layers[0]?.key ?? null });
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
      case 'report': set({ report: ev.report }); return;
      case 'done': set({ runStatus: 'done', progress: s.progress ? { ...s.progress, label: 'Simulation complete' } : null }); return;
      case 'error': set({ runStatus: 'error' }); get().addMessage({ role: 'assistant', kind: 'text', text: `Engine error: ${ev.message}` }); return;
    }
  },
}));

/** Status name for persona index i at step t (defaults to 'unaware'). */
export const statusOf = (statusAt: Uint8Array[], t: number, i: number) => STATUS_CODES[statusAt[Math.min(t, statusAt.length - 1)]?.[i] ?? 0];
