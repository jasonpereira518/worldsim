'use client';
import { useEffect, useRef, useState } from 'react';
import type { Map as MLMap, MapGeoJSONFeature, MapMouseEvent } from 'maplibre-gl';
import { buildStyle, radiusExpr, squareSdf, type StyleData } from '@/lib/map/style';
import { statusOf, useStore } from '@/lib/store';
import { STATUS_INTENSITY, type Frame, type Persona } from '@/lib/sim/types';
import BubbleOverlay from './BubbleOverlay';

const fc = (features: GeoJSON.Feature[]): GeoJSON.FeatureCollection => ({ type: 'FeatureCollection', features });

/** Great-circle arc so long flows do not cut straight across the Mercator plane. */
function arc(from: [number, number], to: [number, number], n = 24): [number, number][] {
  const r = Math.PI / 180;
  const [lon1, lat1, lon2, lat2] = [from[0] * r, from[1] * r, to[0] * r, to[1] * r];
  const d = 2 * Math.asin(Math.sqrt(Math.sin((lat2 - lat1) / 2) ** 2 + Math.cos(lat1) * Math.cos(lat2) * Math.sin((lon2 - lon1) / 2) ** 2));
  if (d < 1e-6) return [from, to];
  const pts: [number, number][] = [];
  for (let i = 0; i <= n; i++) {
    const f = i / n, A = Math.sin((1 - f) * d) / Math.sin(d), B = Math.sin(f * d) / Math.sin(d);
    const x = A * Math.cos(lat1) * Math.cos(lon1) + B * Math.cos(lat2) * Math.cos(lon2);
    const y = A * Math.cos(lat1) * Math.sin(lon1) + B * Math.cos(lat2) * Math.sin(lon2);
    const z = A * Math.sin(lat1) + B * Math.sin(lat2);
    pts.push([Math.atan2(y, x) / r, Math.atan2(z, Math.sqrt(x * x + y * y)) / r]);
  }
  return pts;
}

function buildData(personas: Persona[], statusAt: Uint8Array[], t: number, frames: Frame[]): StyleData {
  const dots: GeoJSON.Feature[] = [], inst: GeoJSON.Feature[] = [];
  personas.forEach((p, i) => {
    const status = statusOf(statusAt, t, i);
    const pop = p.population_represented;
    (p.kind === 'people' ? dots : inst).push({ type: 'Feature', geometry: { type: 'Point', coordinates: [p.location.lon, p.location.lat] }, properties: { id: p.id, pop, status, isum: pop * STATUS_INTENSITY[status] } });
  });
  const flows: GeoJSON.Feature[] = frames.slice(Math.max(0, t - 2), t + 1).flatMap((f) => f.flows).map((fl) => ({ type: 'Feature', geometry: { type: 'LineString', coordinates: arc(fl.from, fl.to) }, properties: { weight: fl.weight, kind: fl.kind } }));
  return { dots: fc(dots), institutions: fc(inst), flows: fc(flows) };
}

const DASH = [[0, 4, 3], [0.5, 4, 2.5], [1, 4, 2], [1.5, 4, 1.5], [2, 4, 1], [2.5, 4, 0.5], [3, 4, 0], [0, 0.5, 3, 3.5], [0, 1, 3, 3], [0, 1.5, 3, 2.5], [0, 2, 3, 2], [0, 2.5, 3, 1.5], [0, 3, 3, 1], [0, 3.5, 3, 0.5]];

export default function MapView() {
  const container = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MLMap | null>(null);
  const dataRef = useRef<StyleData | null>(null);
  const [map, setMap] = useState<MLMap | null>(null);
  const [, setTick] = useState(0);
  const theme = useStore((s) => s.theme);
  const personas = useStore((s) => s.personas);
  const statusAt = useStore((s) => s.statusAt);
  const frames = useStore((s) => s.frames);
  const playhead = useStore((s) => s.playhead);
  const layers = useStore((s) => s.layers);
  const zoomRequest = useStore((s) => s.zoomRequest);
  const selectPersona = useStore((s) => s.selectPersona);

  useEffect(() => {
    let m: MLMap | undefined;
    let cancelled = false;
    (async () => {
      const ml = await import('maplibre-gl');
      ml.setWorkerUrl('/maplibre-gl-worker.mjs'); // served from public/, see scripts/copy-worker.mjs
      if (cancelled || !container.current) return;
      const initialTheme = document.documentElement.getAttribute('data-theme') === 'dark' ? 'dark' : 'light';
      const map: MLMap = new ml.Map({ container: container.current, style: buildStyle(initialTheme), center: [15, 22], zoom: 1.5, minZoom: 0.7, maxZoom: 17, attributionControl: { compact: true }, renderWorldCopies: false });
      m = map;
      map.addControl(new ml.NavigationControl({ showCompass: false }), 'top-right');
      map.on('style.load', () => { if (!map.hasImage('square')) map.addImage('square', squareSdf(), { sdf: true }); });
      map.on('move', () => setTick((x) => x + 1));
      const pick = (e: MapMouseEvent & { features?: MapGeoJSONFeature[] }) => { const id = e.features?.[0]?.properties?.id; if (typeof id === 'string') selectPersona(id); };
      map.on('click', 'dots-point', pick);
      map.on('click', 'institutions', pick);
      map.on('click', 'dots-cluster', async (e) => {
        const f = e.features?.[0]; if (!f) return;
        const src = map.getSource('dots') as import('maplibre-gl').GeoJSONSource;
        const z = await src.getClusterExpansionZoom(f.properties.cluster_id as number);
        map.easeTo({ center: (f.geometry as GeoJSON.Point).coordinates as [number, number], zoom: Math.min(z, 12), duration: 500 });
      });
      for (const id of ['dots-point', 'dots-cluster', 'institutions']) {
        map.on('mouseenter', id, () => { map.getCanvas().style.cursor = 'pointer'; });
        map.on('mouseleave', id, () => { map.getCanvas().style.cursor = ''; });
      }
      map.on('load', () => { map.fitBounds([[-170, -56], [179, 74]], { padding: 8, duration: 0 }); mapRef.current = map; setMap(map); });
    })();
    return () => { cancelled = true; m?.remove(); mapRef.current = null; };
  }, [selectPersona]);

  // Data at the playhead
  useEffect(() => {
    if (!map) return;
    const data = buildData(personas, statusAt, playhead, frames);
    dataRef.current = data;
    const set = (id: string, d: GeoJSON.FeatureCollection) => (map.getSource(id) as import('maplibre-gl').GeoJSONSource | undefined)?.setData(d);
    set('dots', data.dots); set('institutions', data.institutions); set('flows', data.flows);
  }, [map, personas, statusAt, playhead, frames]);

  // Theme: rebuild the single style with current data
  useEffect(() => {
    if (!map) return;
    map.setStyle(buildStyle(theme, dataRef.current ?? undefined));
  }, [map, theme]);

  // Layer toggles
  useEffect(() => {
    if (!map) return;
    const vis = (ids: string[], on: boolean) => ids.forEach((id) => map.getLayer(id) && map.setLayoutProperty(id, 'visibility', on ? 'visible' : 'none'));
    const apply = () => { vis(['dots-point', 'dots-cluster', 'dots-cluster-label', 'dots-pulse'], layers.dots); vis(['institutions'], layers.institutions); vis(['flows'], layers.flows); };
    apply();
    map.on('style.load', apply);
    return () => { map.off('style.load', apply); };
  }, [map, layers]);

  // Pulse + flow particles (skipped under reduced motion)
  useEffect(() => {
    if (!map || window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
    let raf = 0, last = 0;
    const loop = (now: number) => {
      raf = requestAnimationFrame(loop);
      if (now - last < 66 || !map.isStyleLoaded()) return;
      last = now;
      const k = now / 1000;
      if (map.getLayer('flows')) map.setPaintProperty('flows', 'line-dasharray', DASH[Math.floor(k * 12) % DASH.length]);
      if (map.getLayer('dots-pulse')) {
        const s = 0.5 + 0.5 * Math.sin(k * 3);
        map.setPaintProperty('dots-pulse', 'circle-radius', ['*', radiusExpr(['get', 'pop']), 1 + 0.9 * s]);
        map.setPaintProperty('dots-pulse', 'circle-stroke-opacity', 0.4 * (1 - s));
      }
    };
    raf = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(raf);
  }, [map]);

  useEffect(() => {
    if (map && zoomRequest) map.flyTo({ center: zoomRequest.center, zoom: zoomRequest.zoom, duration: 900 });
  }, [map, zoomRequest]);

  return (
    <div className="absolute inset-0">
      <div ref={container} className="h-full w-full" role="region" aria-label="World map" />
      {map && <BubbleOverlay map={map} />}
    </div>
  );
}
