// WCAG 2.x contrast for the design tokens in globals.css (both themes). Text pairs must reach 4.5:1 (AA, normal text).
import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';

const css = readFileSync(new URL('../app/globals.css', import.meta.url), 'utf8');
const block = (selector: string) => {
  const m = css.match(new RegExp(`${selector.replace(/[[\]"=]/g, (c) => `\\${c}`)}\\s*\\{([^}]*)\\}`));
  if (!m) throw new Error(`no block for ${selector}`);
  return Object.fromEntries([...m[1].matchAll(/--([\w-]+):\s*(#[0-9a-f]{6})/gi)].map((x) => [x[1], x[2]]));
};
const lum = (hex: string) => {
  const [r, g, b] = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255).map((c) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4));
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
};
const ratio = (a: string, b: string) => { const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p); return (x + 0.05) / (y + 0.05); };

describe('design tokens meet WCAG AA', () => {
  for (const [name, sel] of [['light', ':root'], ['dark', ':root[data-theme="dark"]']] as const) {
    it(`${name}: ink and muted text on bg and surface`, () => {
      const t = block(sel);
      for (const fg of ['ink', 'muted']) for (const bg of ['bg', 'surface']) {
        expect(ratio(t[fg], t[bg]), `${name} ${fg} on ${bg}`).toBeGreaterThanOrEqual(4.5);
      }
      expect(ratio(t.bg, t.ink)).toBeGreaterThanOrEqual(7); // inverted pills (bg text on ink) reach AAA
    });
  }
});
