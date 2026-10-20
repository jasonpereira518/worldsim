import { describe, expect, it } from 'vitest';
import { bubbleCap, layoutBubbles } from './bubbles';

describe('bubble layout', () => {
  const vp = { width: 1200, height: 800 };
  const anchors = Array.from({ length: 30 }, (_, i) => ({ id: `b${i}`, x: 600 + (i % 5) * 8, y: 400 + Math.floor(i / 5) * 8, w: 200, h: 50, priority: 30 - i }));

  it('never overlaps and respects the cap', () => {
    const placed = layoutBubbles(anchors, vp, 8);
    expect(placed.length).toBeLessThanOrEqual(8);
    expect(placed.length).toBeGreaterThan(1);
    for (let i = 0; i < placed.length; i++) for (let j = i + 1; j < placed.length; j++) {
      const a = placed[i], b = placed[j];
      const overlap = a.left < b.left + 200 && a.left + 200 > b.left && a.top < b.top + 50 && a.top + 50 > b.top;
      expect(overlap, `${a.id} overlaps ${b.id}`).toBe(false);
    }
  });
  it('places the highest priority first and skips offscreen anchors', () => {
    const placed = layoutBubbles([...anchors, { id: 'off', x: -50, y: 10, w: 200, h: 50, priority: 999 }], vp, 3);
    expect(placed[0].id).toBe('b0');
    expect(placed.find((p) => p.id === 'off')).toBeUndefined();
  });
  it('scales the cap with zoom', () => {
    expect(bubbleCap(1)).toBe(6);
    expect(bubbleCap(12)).toBe(24);
  });
});
