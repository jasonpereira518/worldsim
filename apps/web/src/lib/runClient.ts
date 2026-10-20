// Owns the connection to the sim service: create runs, consume the SSE stream, send follow-ups.
import { useStore } from './store';
import type { ChatAction, DataCatalogEntry, ScenarioSpec, ServerEvent } from './sim/types';

let es: EventSource | null = null;
const EVENT_TYPES: ServerEvent['type'][] = ['personas', 'frame', 'progress', 'summary', 'done', 'error'];
const FOLLOW_UP = /\b(zoom|go to|show me|fly to|look at|why|explain|how did|when did|what if|compare|rerun|re-run|branch)\b/i;

export const EXAMPLES = [
  'A novel H5N1 variant begins human-to-human transmission in Vietnam',
  'Apple launches a $499 AR headset globally next month',
  'The EU imposes a 40% tariff on Chinese EVs',
  'A magnitude 8.1 quake hits Istanbul',
];

const say = (text: string) => useStore.getState().addMessage({ role: 'assistant', kind: 'text', text });

export function stopRun() {
  es?.close();
  es = null;
  const s = useStore.getState();
  if (s.runStatus === 'streaming') s.setRunStatus('done');
}

export async function submitPrompt(raw: string) {
  const prompt = raw.trim();
  if (!prompt) return;
  const s = useStore.getState();
  s.addMessage({ role: 'user', kind: 'text', text: prompt });
  if (prompt.startsWith('/')) return slash(prompt);
  if (s.runStatus === 'awaiting_answer' && s.pendingPrompt) return createRun(s.pendingPrompt, { origin: prompt });
  if (s.runId && FOLLOW_UP.test(prompt)) return followUp(s.runId, prompt);
  return createRun(prompt);
}

async function createRun(prompt: string, answers?: { origin: string }) {
  const s = useStore.getState();
  stopRun();
  s.setRunStatus('parsing');
  s.setPendingPrompt(null);
  const res = await fetch('/api/runs', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ prompt, answers }) });
  if (!res.ok) { s.setRunStatus('error'); return say(`Could not parse that (${res.status}). Try a shorter description of the event.`); }
  const { run_id, spec } = (await res.json()) as { run_id: string; spec: ScenarioSpec };
  s.addMessage({ role: 'assistant', kind: 'spec', spec });
  if (spec.clarifying_question) {
    s.setPendingPrompt(prompt);
    s.setRunStatus('awaiting_answer');
    return say(spec.clarifying_question);
  }
  s.beginRun(run_id, spec);
  es = new EventSource(`/api/runs/${run_id}/stream`);
  for (const type of EVENT_TYPES) {
    es.addEventListener(type, (e) => {
      const ev = JSON.parse((e as MessageEvent).data) as ServerEvent;
      useStore.getState().applyServerEvent(ev);
      if (ev.type === 'done' || ev.type === 'error') stopRun();
    });
  }
  es.onerror = () => { if (useStore.getState().runStatus === 'streaming') { say('Stream interrupted. Scrub what was received or start a new scenario.'); stopRun(); } };
}

async function followUp(runId: string, message: string) {
  const res = await fetch(`/api/runs/${runId}/chat`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ message }) });
  if (!res.ok) return say('That follow-up failed. Try "zoom into Brazil" or "why did Turkey get hit".');
  const { reply, action } = (await res.json()) as { reply: string; action?: ChatAction };
  say(reply);
  if (action?.type === 'zoom') useStore.getState().requestZoom(action.center, action.zoom);
}

async function slash(cmd: string) {
  const s = useStore.getState();
  const name = cmd.split(/\s+/)[0].toLowerCase();
  switch (name) {
    case '/assumptions':
      if (!s.spec) return say('No scenario yet. Describe an event first.');
      return s.addMessage({ role: 'assistant', kind: 'list', items: s.spec.assumptions.map((a) => `${a.text} — ${a.origin}, ${a.confidence} confidence`) });
    case '/sources': {
      s.setDataDrawerOpen(true);
      const res = await fetch('/api/data/catalog');
      if (!res.ok) return say(`Opened Data & assumptions. The catalog is not available yet (${res.status}).`);
      const catalog = (await res.json()) as DataCatalogEntry[];
      const stale = catalog.filter((c) => c.stale);
      return say(`Opened Data & assumptions: ${catalog.length} sources, snapshot ${catalog[0]?.snapshot_id}. ${stale.length ? `Stale: ${stale.map((c) => c.name).join('; ')}.` : 'All fresh.'}`);
    }
    case '/reset': stopRun(); s.reset(); return say('Cleared. Describe a new event to simulate.');
    case '/compare': case '/export': return say(`${name} arrives in Milestone 4 (branching, compare view, PDF/Markdown export).`);
    default: return say('Commands: /assumptions, /sources, /compare, /export, /reset');
  }
}
