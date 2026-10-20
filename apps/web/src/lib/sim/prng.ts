export type Rng = () => number;

/** 32-bit FNV-1a hash; used for seeds and per-persona deterministic traits. */
export function fnv1a(str: string): number {
  let h = 0x811c9dc5;
  for (let i = 0; i < str.length; i++) {
    h ^= str.charCodeAt(i);
    h = Math.imul(h, 0x01000193);
  }
  return h >>> 0;
}

/** mulberry32: small, fast, deterministic. Returns floats in [0, 1). */
export function mulberry32(seed: number): Rng {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/** Deterministic [0,1) value for an id + salt, without advancing any stream. */
export function unit(id: string, salt: string): number {
  return fnv1a(`${id}|${salt}`) / 4294967296;
}

export const clamp01 = (x: number) => (x < 0 ? 0 : x > 1 ? 1 : x);
