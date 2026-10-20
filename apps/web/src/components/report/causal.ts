// Layered layout for a small causal graph: column = longest path from a source, ignoring back edges (cycles).
import type { CausalGraph } from '@/lib/sim/types';

export interface Placed { id: string; label: string; col: number; row: number }

export function layout(g: CausalGraph): { nodes: Placed[]; back: Set<string>; cols: number; rows: number } {
  const out = new Map<string, string[]>();
  g.nodes.forEach((n) => out.set(n.id, []));
  g.edges.forEach((e) => out.get(e.from)?.push(e.to));
  // find back edges with a DFS so the remaining graph is a DAG
  const back = new Set<string>();
  const state = new Map<string, 0 | 1 | 2>();
  const dfs = (u: string) => {
    state.set(u, 1);
    for (const v of out.get(u) ?? []) {
      if (state.get(v) === 1) back.add(`${u}>${v}`);
      else if (!state.get(v)) dfs(v);
    }
    state.set(u, 2);
  };
  g.nodes.forEach((n) => { if (!state.get(n.id)) dfs(n.id); });
  const level = new Map<string, number>(g.nodes.map((n) => [n.id, 0]));
  for (let i = 0; i < g.nodes.length; i++) {
    for (const e of g.edges) {
      if (back.has(`${e.from}>${e.to}`)) continue;
      level.set(e.to, Math.max(level.get(e.to) ?? 0, (level.get(e.from) ?? 0) + 1));
    }
  }
  const rowsUsed = new Map<number, number>();
  const nodes = g.nodes.map((n) => {
    const col = level.get(n.id) ?? 0;
    const row = rowsUsed.get(col) ?? 0;
    rowsUsed.set(col, row + 1);
    return { id: n.id, label: n.label, col, row };
  });
  return { nodes, back, cols: Math.max(...nodes.map((n) => n.col), 0) + 1, rows: Math.max(...rowsUsed.values(), 1) };
}

/** Greedy word wrap for SVG text. */
export function wrap(text: string, width = 24): string[] {
  const lines: string[] = [];
  let cur = '';
  for (const w of text.split(' ')) {
    if ((cur + ' ' + w).trim().length > width && cur) { lines.push(cur); cur = w; } else cur = (cur + ' ' + w).trim();
  }
  if (cur) lines.push(cur);
  return lines.slice(0, 4);
}
