import { describe, expect, it } from 'vitest';
import { layout, wrap } from './causal';

describe('causal layout', () => {
  it('orders a chain left to right and survives cycles', () => {
    const g = { nodes: [{ id: 'a', label: 'A' }, { id: 'b', label: 'B' }, { id: 'c', label: 'C' }],
      edges: [{ from: 'a', to: 'b' }, { from: 'b', to: 'c' }, { from: 'c', to: 'b' }] };
    const { nodes, back, cols } = layout(g);
    const col = Object.fromEntries(nodes.map((n) => [n.id, n.col]));
    expect(col.a).toBeLessThan(col.b);
    expect(col.b).toBeLessThan(col.c);
    expect(back.size).toBe(1);
    expect(cols).toBe(3);
  });
  it('wraps long labels', () => {
    expect(wrap('Hospitals over capacity in 12 countries', 16).length).toBeGreaterThan(1);
  });
});
