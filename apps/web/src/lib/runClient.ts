// Owns the connection to the sim service: create runs and branches, consume the SSE stream, send follow-ups.
import { useStore, type LiveFeed } from './store';
import type { ChatAction, DataCatalogEntry, RunListItem, ScenarioSpec, ServerEvent } from './sim/types';

let es: EventSource | null = null;
const EVENT_TYPES: ServerEvent['type'][] = ['personas', 'meta', 'agent', 'spec', 'scale', 'frame', 'progress', 'summary', 'report', 'done', 'error'];
const FOLLOW_UP = /\b(zoom|go to|show me|fly to|look at|focus on|why|explain|how did|when did|what happened|what if|compare|versus|baseline|rerun|re-run|instead|suppose|branch|show only)\b/i;

export const EXAMPLES = [
  'Apple launches a $499 AR headset worldwide on Dec 1, 2026',
  'A novel H5N1 variant begins human-to-human transmission in Vietnam',
  'The EU imposes a 40% tariff on Chinese EVs',
  'A magnitude 8.1 quake hits Istanbul',
];

const say = (text: string) => useStore.getState().addMessage({ role: 'assistant', kind: 'text', text });
const json = (body: unknown) => ({ method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });

export function stopRun() {
  es?.close();
  es = null;
  const s = useStore.getState();
  if (s.runStatus === 'streaming') s.setRunStatus('done');
}

export async function submitPrompt(raw: string) {
  const prompt = raw.trim();
  const s = useStore.getState();
  if (!prompt || s.readOnly) return;
  s.addMessage({ role: 'user', kind: 'text', text: prompt });
  if (prompt.startsWith('/')) return slash(prompt);
  if (s.runStatus === 'awaiting_answer' && s.pendingPrompt) return createRun({ prompt: s.pendingPrompt, answers: { origin: prompt } });
  if (s.runId && FOLLOW_UP.test(prompt)) return followUp(s.runId, prompt);
  return createRun({ prompt });
}

interface CreateBody { prompt: string; answers?: { origin: string }; assumptions?: Record<string, number>; parent_run_id?: string; label?: string; seed?: number }

export async function createRun(body: CreateBody) {
  const s = useStore.getState();
  stopRun();
  s.setRunStatus('parsing');
  s.setPendingPrompt(null);
  const res = await fetch('/api/runs', json(body));
  if (!res.ok) {
    s.setRunStatus('error');
    const err = await res.json().catch(() => ({}));
    return say(res.status === 422 ? 'That prompt could not be read. Describe the event in one sentence.' : `Could not start the run (${res.status}). ${err.error ?? ''}`);
  }
  const { run_id, spec, parent_run_id } = (await res.json()) as { run_id: string; spec: ScenarioSpec; parent_run_id?: string | null };
  s.addMessage({ role: 'assistant', kind: 'spec', spec, runId: run_id });
  if (spec.clarifying_question) {
    s.setPendingPrompt(body.prompt);
    s.setRunStatus('awaiting_answer');
    return say(spec.clarifying_question);
  }
  streamRun(run_id, spec, parent_run_id ?? null);
}

export function streamRun(runId: string, spec: ScenarioSpec, parentRunId: string | null = null) {
  stopRun();
  useStore.getState().beginRun(runId, spec, parentRunId);
  if (!useStore.getState().readOnly) history.replaceState(null, '', `/?run=${runId}`);
  es = new EventSource(`/api/runs/${runId}/stream`);
  for (const type of EVENT_TYPES) {
    es.addEventListener(type, (e) => {
      const ev = JSON.parse((e as MessageEvent).data) as ServerEvent;
      useStore.getState().applyServerEvent(ev);
      if (ev.type === 'done' || ev.type === 'error') { stopRun(); void refreshHistory(); }
    });
  }
  es.onerror = () => { if (useStore.getState().runStatus === 'streaming') { say('Stream interrupted. Scrub what was received or start a new scenario.'); stopRun(); } };
}

/** Replays a saved run (history, shared links). Same seed and config → identical frames. */
let loading: string | null = null;
export async function loadRun(runId: string) {
  if (loading === runId) return;
  loading = runId;
  const res = await fetch(`/api/runs/${encodeURIComponent(runId)}`).finally(() => { loading = null; });
  if (!res.ok) return say(`Run ${runId} was not found.`);
  const cfg = (await res.json()) as { spec: ScenarioSpec; parent_run_id?: string | null };
  useStore.getState().addMessage({ role: 'assistant', kind: 'spec', spec: cfg.spec, runId });
  streamRun(runId, cfg.spec, cfg.parent_run_id ?? null);
}

/** Edited assumption chip → a branch run with that value fixed (same seed, so the difference is the edit). */
export async function editAssumption(id: string, value: number) {
  const s = useStore.getState();
  if (!s.runId || !s.spec) return;
  const a = s.spec.assumptions.find((x) => x.id === id) ?? s.report?.appendix.assumptions.find((x) => x.id === id);
  s.addMessage({ role: 'user', kind: 'text', text: `Set "${a?.text ?? id}" to ${value}${a?.unit ? ' ' + a.unit : ''}` });
  return createRun({ prompt: s.spec.prompt, parent_run_id: s.runId, assumptions: { [id]: value }, label: `${id} = ${value}` });
}

async function followUp(runId: string, message: string) {
  const s = useStore.getState();
  const res = await fetch(`/api/runs/${runId}/chat`, json({ message, t: s.playhead }));
  if (!res.ok) return say('That follow-up failed. Try "zoom into Brazil", "explain why Japan adopted" or "what if borders close on day 10".');
  const { reply, action } = (await res.json()) as { reply: string; action?: ChatAction };
  say(reply);
  if (!action) return;
  if (action.type === 'zoom') s.requestZoom(action.center, action.zoom);
  else if (action.type === 'layers') s.setLayers(action.layers);
  else if (action.type === 'compare') s.setCompare({ a: action.a, b: action.b });
  else if (action.type === 'branch') {
    s.addMessage({ role: 'assistant', kind: 'spec', spec: action.spec, runId: action.run_id });
    streamRun(action.run_id, action.spec, action.parent_run_id);
  }
}

export async function refreshHistory() {
  const res = await fetch('/api/runs').catch(() => null);
  if (res?.ok) useStore.getState().setHistory((await res.json()) as RunListItem[]);
}

export async function loadLive() {
  const res = await fetch('/api/feeds').catch(() => null);
  if (res?.ok) useStore.getState().setLive(((await res.json()) as { feeds: LiveFeed[] }).feeds);
}

export const shareLink = (runId: string) => `${location.origin}/r/${runId}`;

async function slash(cmd: string) {
  const s = useStore.getState();
  const name = cmd.split(/\s+/)[0].toLowerCase();
  switch (name) {
    case '/assumptions':
      if (!s.spec) return say('No scenario yet. Describe an event first.');
      s.setDataDrawerOpen(true);
      return s.addMessage({ role: 'assistant', kind: 'list', items: (s.report?.appendix.assumptions ?? s.spec.assumptions).map((a) =>
        `${a.text}${a.value != null ? ` = ${a.value}${a.unit ? ' ' + a.unit : ''}` : ''}${a.low != null && a.high != null && a.low !== a.high ? ` (range ${a.low}–${a.high})` : ''} — ${a.origin}, ${a.confidence} confidence${a.source ? `; ${a.source}` : ''}`) });
    case '/sources': {
      s.setDataDrawerOpen(true);
      const res = await fetch('/api/data/catalog');
      if (!res.ok) return say(`Opened Data & assumptions. The catalog is not available yet (${res.status}).`);
      const catalog = (await res.json()) as DataCatalogEntry[];
      const stale = catalog.filter((c) => c.stale);
      return say(`Opened Data & assumptions: ${catalog.length} sources, snapshot ${catalog[0]?.snapshot_id}. ${stale.length ? `Stale: ${stale.map((c) => c.name).join('; ')}.` : 'All fresh.'}`);
    }
    case '/compare':
      if (!s.runId) return say('No run yet.');
      if (!s.parentRunId) return say('This run has no baseline. Ask a "what if" (for example "what if borders close on day 10") to branch it first.');
      s.setCompare({ a: s.parentRunId, b: s.runId });
      return say('Opened the comparison with the baseline run.');
    case '/export':
      if (!s.runId || s.runStatus !== 'done') return say('Export is available once the run completes.');
      window.open(`/report/${s.runId}`, '_blank', 'noopener');
      return say(`Opened the full report. Download Markdown from /api/runs/${s.runId}/report.md, or print the report page to PDF.`);
    case '/share':
      if (!s.runId) return say('No run yet.');
      try { await navigator.clipboard.writeText(shareLink(s.runId)); } catch {}
      return say(`Read-only link (copied): ${shareLink(s.runId)}`);
    case '/runs': s.setChatTab('runs'); void refreshHistory(); return say('Opened run history.');
    case '/reset': stopRun(); s.reset(); return say('Cleared. Describe a new event to simulate.');
    default: return say('Commands: /assumptions, /sources, /compare, /export, /share, /runs, /reset');
  }
}
