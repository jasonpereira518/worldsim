// One MapLibre style = monochrome basemap (OpenFreeMap vector tiles, OpenMapTiles schema) + Worldsim data layers.
// Theme switch rebuilds the whole style with the current data, so there is exactly one place colors are defined.
import type { ExpressionSpecification, StyleSpecification } from 'maplibre-gl';
import type { Theme } from '../sim/types';

export type Palette = { land: string; water: string; waterway: string; admin0: string; admin1: string; road: string; roadMajor: string; building: string; label: string; halo: string; ink: string; muted: string; gray2: string; bg: string };
export const MAP_COLORS: Record<Theme, Palette> = {
  light: { land: '#FFFFFF', water: '#EFEFEF', waterway: '#E5E5E5', admin0: '#CFCFCF', admin1: '#E5E5E5', road: '#E5E5E5', roadMajor: '#D9D9D9', building: '#F0F0F0', label: '#6B6B6B', halo: '#FFFFFF', ink: '#0A0A0A', muted: '#6B6B6B', gray2: '#BFBFBF', bg: '#FFFFFF' },
  dark: { land: '#000000', water: '#0F0F0F', waterway: '#1A1A1A', admin0: '#333333', admin1: '#1F1F1F', road: '#1F1F1F', roadMajor: '#2A2A2A', building: '#0A0A0A', label: '#8F8F8F', halo: '#000000', ink: '#FFFFFF', muted: '#8F8F8F', gray2: '#4A4A4A', bg: '#000000' },
};

export const EMPTY_FC: GeoJSON.FeatureCollection = { type: 'FeatureCollection', features: [] };
export interface StyleData { dots: GeoJSON.FeatureCollection; institutions: GeoJSON.FeatureCollection; flows: GeoJSON.FeatureCollection }

const TILES = 'https://tiles.openfreemap.org/planet';
const GLYPHS = 'https://tiles.openfreemap.org/fonts/{fontstack}/{range}.pbf';
const FONT = ['Noto Sans Regular'];
const name: ExpressionSpecification = ['coalesce', ['get', 'name:en'], ['get', 'name']];

/** Radius in px from represented population (log scale). Shared by points, clusters, and square icons. */
export const radiusExpr = (popExpr: ExpressionSpecification): ExpressionSpecification => [
  'interpolate', ['linear'], ['log10', ['max', popExpr, 1]], 3, 2.5, 5, 4, 6, 7, 7, 13, 7.6, 22, 8.3, 32,
];

export function statusFill(c: Palette): ExpressionSpecification {
  return ['match', ['get', 'status'], 'unaware', c.bg, 'aware', c.gray2, 'reacting', c.muted, 'affected', c.ink, 'recovered', c.bg, 'adopted', c.ink, 'opposed', c.muted, c.bg];
}
export function statusStroke(c: Palette): ExpressionSpecification {
  return ['match', ['get', 'status'], 'unaware', c.muted, 'recovered', c.ink, 'opposed', c.ink, c.bg];
}
const statusStrokeWidth: ExpressionSpecification = ['match', ['get', 'status'], 'unaware', 1, 'recovered', 2, 'opposed', 2, 0.75];

/** Population-weighted mean intensity of a cluster: Σ(pop·intensity) / Σ(pop). */
const clusterRatio: ExpressionSpecification = ['/', ['get', 'isum'], ['max', ['get', 'pop'], 1]];

export function buildStyle(theme: Theme, data: StyleData = { dots: EMPTY_FC, institutions: EMPTY_FC, flows: EMPTY_FC }): StyleSpecification {
  const c = MAP_COLORS[theme];
  const ramp: ExpressionSpecification = ['interpolate', ['linear'], clusterRatio, 0, c.bg, 0.3, c.gray2, 0.6, c.muted, 1, c.ink];
  return {
    version: 8,
    glyphs: GLYPHS,
    sources: {
      omt: { type: 'vector', url: TILES },
      dots: {
        type: 'geojson', data: data.dots, cluster: true, clusterRadius: 36, clusterMaxZoom: 11,
        clusterProperties: { pop: ['+', ['get', 'pop']], isum: ['+', ['get', 'isum']] },
      },
      institutions: { type: 'geojson', data: data.institutions },
      flows: { type: 'geojson', data: data.flows },
    },
    layers: [
      { id: 'land', type: 'background', paint: { 'background-color': c.land } },
      { id: 'water', type: 'fill', source: 'omt', 'source-layer': 'water', filter: ['!=', ['get', 'brunnel'], 'tunnel'], paint: { 'fill-color': c.water } },
      { id: 'waterway', type: 'line', source: 'omt', 'source-layer': 'waterway', minzoom: 8, paint: { 'line-color': c.waterway, 'line-width': ['interpolate', ['linear'], ['zoom'], 8, 0.5, 14, 1.5] } },
      { id: 'building', type: 'fill', source: 'omt', 'source-layer': 'building', minzoom: 13, paint: { 'fill-color': c.building, 'fill-outline-color': c.road } },
      { id: 'roads-minor', type: 'line', source: 'omt', 'source-layer': 'transportation', minzoom: 11,
        filter: ['match', ['get', 'class'], ['secondary', 'tertiary', 'minor', 'service', 'residential'], true, false],
        paint: { 'line-color': c.road, 'line-width': ['interpolate', ['linear'], ['zoom'], 11, 0.4, 16, 2] } },
      { id: 'roads-major', type: 'line', source: 'omt', 'source-layer': 'transportation', minzoom: 6,
        filter: ['match', ['get', 'class'], ['motorway', 'trunk', 'primary'], true, false],
        paint: { 'line-color': c.roadMajor, 'line-width': ['interpolate', ['linear'], ['zoom'], 6, 0.4, 14, 2.5] } },
      { id: 'boundary-admin1', type: 'line', source: 'omt', 'source-layer': 'boundary', minzoom: 4,
        filter: ['all', ['>=', ['get', 'admin_level'], 3], ['<=', ['get', 'admin_level'], 6], ['!=', ['get', 'maritime'], 1], ['!=', ['get', 'disputed'], 1]],
        paint: { 'line-color': c.admin1, 'line-width': 0.8, 'line-dasharray': [3, 2] } },
      { id: 'boundary-admin0', type: 'line', source: 'omt', 'source-layer': 'boundary',
        filter: ['all', ['==', ['get', 'admin_level'], 2], ['!=', ['get', 'maritime'], 1], ['!=', ['get', 'disputed'], 1]],
        paint: { 'line-color': c.admin0, 'line-width': ['interpolate', ['linear'], ['zoom'], 0, 0.5, 6, 1, 12, 1.6] } },
      { id: 'boundary-disputed', type: 'line', source: 'omt', 'source-layer': 'boundary',
        filter: ['all', ['==', ['get', 'admin_level'], 2], ['!=', ['get', 'maritime'], 1], ['==', ['get', 'disputed'], 1]],
        paint: { 'line-color': c.admin0, 'line-width': 0.8, 'line-dasharray': [2, 2] } },
      { id: 'place-country', type: 'symbol', source: 'omt', 'source-layer': 'place', maxzoom: 7, filter: ['==', ['get', 'class'], 'country'],
        layout: { 'text-field': name, 'text-font': FONT, 'text-transform': 'uppercase', 'text-letter-spacing': 0.08,
          'text-size': ['interpolate', ['linear'], ['zoom'], 1, ['-', 12, ['*', 1.2, ['get', 'rank']]], 6, 14], 'text-max-width': 6 },
        paint: { 'text-color': c.label, 'text-halo-color': c.halo, 'text-halo-width': 1.2 } },
      { id: 'place-state', type: 'symbol', source: 'omt', 'source-layer': 'place', minzoom: 4, maxzoom: 10, filter: ['==', ['get', 'class'], 'state'],
        layout: { 'text-field': name, 'text-font': FONT, 'text-transform': 'uppercase', 'text-letter-spacing': 0.1, 'text-size': 10 },
        paint: { 'text-color': c.label, 'text-halo-color': c.halo, 'text-halo-width': 1, 'text-opacity': 0.8 } },
      { id: 'place-city', type: 'symbol', source: 'omt', 'source-layer': 'place', minzoom: 3,
        filter: ['match', ['get', 'class'], ['city', 'town'], true, false],
        layout: { 'text-field': name, 'text-font': FONT, 'symbol-sort-key': ['get', 'rank'],
          'text-size': ['interpolate', ['linear'], ['zoom'], 3, ['case', ['==', ['get', 'capital'], 2], 11, 9], 10, 14], 'text-anchor': 'top', 'text-offset': [0, 0.4] },
        paint: { 'text-color': c.label, 'text-halo-color': c.halo, 'text-halo-width': 1 } },
      // --- Worldsim data layers ---
      { id: 'flows', type: 'line', source: 'flows', layout: { 'line-cap': 'round' },
        paint: { 'line-color': c.ink, 'line-opacity': 0.55, 'line-width': ['interpolate', ['linear'], ['get', 'weight'], 0, 0.5, 1, 2], 'line-dasharray': [0, 4, 3] } },
      { id: 'dots-cluster', type: 'circle', source: 'dots', filter: ['has', 'point_count'],
        paint: { 'circle-color': ramp, 'circle-radius': radiusExpr(['get', 'pop']), 'circle-stroke-color': c.muted, 'circle-stroke-width': 1, 'circle-opacity': 0.95 } },
      { id: 'dots-cluster-label', type: 'symbol', source: 'dots', filter: ['all', ['has', 'point_count'], ['>=', ['get', 'pop'], 4000000]],
        layout: { 'text-field': ['concat', ['to-string', ['round', ['/', ['get', 'pop'], 1000000]]], 'M'], 'text-font': FONT, 'text-size': 10, 'text-allow-overlap': true },
        paint: { 'text-color': ['case', ['>', clusterRatio, 0.45], c.bg, c.ink] } },
      { id: 'dots-pulse', type: 'circle', source: 'dots',
        filter: ['all', ['!', ['has', 'point_count']], ['match', ['get', 'status'], ['reacting', 'affected', 'adopted'], true, false]],
        paint: { 'circle-color': c.ink, 'circle-opacity': 0, 'circle-radius': radiusExpr(['get', 'pop']), 'circle-stroke-color': c.ink, 'circle-stroke-width': 1, 'circle-stroke-opacity': 0.35 } },
      { id: 'dots-point', type: 'circle', source: 'dots', filter: ['!', ['has', 'point_count']],
        paint: { 'circle-color': statusFill(c), 'circle-radius': radiusExpr(['get', 'pop']), 'circle-stroke-color': statusStroke(c), 'circle-stroke-width': statusStrokeWidth } },
      { id: 'institutions', type: 'symbol', source: 'institutions',
        layout: { 'icon-image': 'square', 'icon-allow-overlap': true, 'icon-ignore-placement': true,
          'icon-size': ['interpolate', ['linear'], ['log10', ['max', ['get', 'pop'], 1]], 2, 0.3, 4, 0.42, 6, 0.75] },
        paint: { 'icon-color': statusFill(c), 'icon-halo-color': statusStroke(c), 'icon-halo-width': ['match', ['get', 'status'], 'unaware', 1, 'recovered', 1.5, 'opposed', 1.5, 0.5] } },
    ],
  };
}

/** Signed-distance-field square for `map.addImage('square', squareSdf(), { sdf: true })`, so icon-color works. */
export function squareSdf(size = 48, buffer = 8): { width: number; height: number; data: Uint8ClampedArray } {
  const data = new Uint8ClampedArray(size * size * 4);
  const half = size / 2 - buffer;
  const radius = 8; // px over which alpha falls from inside to outside
  const cutoff = 0.25; // MapLibre treats alpha 0.75 as the edge
  for (let y = 0; y < size; y++) {
    for (let x = 0; x < size; x++) {
      const dx = Math.abs(x + 0.5 - size / 2);
      const dy = Math.abs(y + 0.5 - size / 2);
      const d = Math.max(dx, dy) - half; // negative inside
      const alpha = Math.round(255 * Math.max(0, Math.min(1, 1 - cutoff - d / radius)));
      data[(y * size + x) * 4 + 3] = alpha;
    }
  }
  return { width: size, height: size, data };
}

/** Every color in a style, for the grayscale guard test. */
export function styleColors(style: StyleSpecification): string[] {
  const out: string[] = [];
  const walk = (v: unknown) => {
    if (typeof v === 'string') { if (/^#[0-9a-f]{3,8}$/i.test(v) || /^(rgb|hsl)a?\(/i.test(v)) out.push(v); }
    else if (Array.isArray(v)) v.forEach(walk);
    else if (v && typeof v === 'object') Object.values(v).forEach(walk);
  };
  walk(style.layers.map((l) => ({ paint: (l as { paint?: unknown }).paint, layout: (l as { layout?: unknown }).layout })));
  return out;
}
