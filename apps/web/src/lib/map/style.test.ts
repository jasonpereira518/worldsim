import { describe, expect, it } from 'vitest';
import { MAP_COLORS, buildStyle, squareSdf, styleColors } from './style';

const isGray = (hex: string) => {
  const m = /^#([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i.exec(hex);
  return !!m && m[1].toLowerCase() === m[2].toLowerCase() && m[2].toLowerCase() === m[3].toLowerCase();
};

describe('map style', () => {
  it.each(['light', 'dark'] as const)('%s theme uses only grayscale colors', (theme) => {
    const colors = styleColors(buildStyle(theme));
    expect(colors.length).toBeGreaterThan(10);
    for (const c of colors) expect(isGray(c), `${c} is not grayscale`).toBe(true);
    for (const c of Object.values(MAP_COLORS[theme])) expect(isGray(c)).toBe(true);
  });
  it('includes the data sources and layers', () => {
    const s = buildStyle('light');
    expect(Object.keys(s.sources)).toEqual(expect.arrayContaining(['omt', 'dots', 'institutions', 'flows']));
    expect(s.layers.map((l) => l.id)).toEqual(expect.arrayContaining(['dots-point', 'dots-cluster', 'institutions', 'flows']));
  });
  it('builds an SDF square: opaque center, transparent corner, edge near 0.75', () => {
    const { width, data } = squareSdf(48, 8);
    const alpha = (x: number, y: number) => data[(y * width + x) * 4 + 3];
    expect(alpha(24, 24)).toBe(255);
    expect(alpha(0, 0)).toBe(0);
    expect(Math.abs(alpha(24, 8) - 191)).toBeLessThanOrEqual(20);
  });
});
