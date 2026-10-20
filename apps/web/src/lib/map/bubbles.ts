// Greedy speech-bubble placement with collision avoidance. Pure, so it is unit-tested without a browser.
export interface Anchor { id: string; x: number; y: number; w: number; h: number; priority: number }
export type Side = 'tr' | 'tl' | 'br' | 'bl' | 't' | 'b' | 'l' | 'r';
export interface Placed { id: string; left: number; top: number; side: Side }
interface Box { l: number; t: number; r: number; b: number }

const overlaps = (a: Box, b: Box) => a.l < b.r && a.r > b.l && a.t < b.b && a.b > b.t;
const OFFSET = 12;

export function layoutBubbles(items: Anchor[], viewport: { width: number; height: number }, cap: number, gap = 6): Placed[] {
  const sorted = [...items].sort((a, b) => b.priority - a.priority || a.id.localeCompare(b.id));
  const boxes: Box[] = [];
  const out: Placed[] = [];
  for (const it of sorted) {
    if (out.length >= cap) break;
    if (it.x < 0 || it.y < 0 || it.x > viewport.width || it.y > viewport.height) continue;
    const candidates: { side: Side; left: number; top: number }[] = [
      { side: 'tr', left: it.x + OFFSET, top: it.y - it.h - OFFSET },
      { side: 'tl', left: it.x - it.w - OFFSET, top: it.y - it.h - OFFSET },
      { side: 'br', left: it.x + OFFSET, top: it.y + OFFSET },
      { side: 'bl', left: it.x - it.w - OFFSET, top: it.y + OFFSET },
      { side: 't', left: it.x - it.w / 2, top: it.y - it.h - OFFSET },
      { side: 'b', left: it.x - it.w / 2, top: it.y + OFFSET },
      { side: 'r', left: it.x + OFFSET, top: it.y - it.h / 2 },
      { side: 'l', left: it.x - it.w - OFFSET, top: it.y - it.h / 2 },
    ];
    for (const c of candidates) {
      const box = { l: c.left - gap, t: c.top - gap, r: c.left + it.w + gap, b: c.top + it.h + gap };
      if (box.l < 0 || box.t < 0 || box.r > viewport.width || box.b > viewport.height) continue;
      if (boxes.some((o) => overlaps(o, box))) continue;
      boxes.push(box);
      out.push({ id: it.id, left: c.left, top: c.top, side: c.side });
      break;
    }
  }
  return out;
}

/** Visible-bubble budget by zoom: ~6 at global zoom, up to 24 when zoomed in. */
export const bubbleCap = (zoom: number) => Math.round(Math.min(24, Math.max(6, 3 + zoom * 1.8)));

export const BUBBLE_WIDTH = 200;
/** Height estimate for a 200px-wide bubble at 12px type before it is rendered. */
export const estimateHeight = (text: string) => 18 + 16 * Math.max(1, Math.ceil((text.length * 6.1) / (BUBBLE_WIDTH - 24)));
