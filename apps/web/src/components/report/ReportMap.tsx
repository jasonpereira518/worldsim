'use client';
import { useEffect, useRef } from 'react';
import type { Map as MLMap } from 'maplibre-gl';
import { buildStyle, EMPTY_FC } from '@/lib/map/style';

/** Final-state map snapshot: the report's first layer as a grayscale choropleth. */
export default function ReportMap({ values }: { values: Record<string, number> }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    let map: MLMap | undefined;
    let cancelled = false;
    (async () => {
      const ml = await import('maplibre-gl');
      ml.setWorkerUrl('/maplibre-gl-worker.mjs');
      const geo = await fetch('/api/data/geo').then((r) => (r.ok ? r.json() : null)).catch(() => null);
      if (cancelled || !ref.current) return;
      const theme = document.documentElement.getAttribute('data-theme') === 'dark' ? 'dark' : 'light';
      map = new ml.Map({ container: ref.current, style: buildStyle(theme, { dots: EMPTY_FC, institutions: EMPTY_FC, flows: EMPTY_FC, countries: geo ?? EMPTY_FC }),
        center: [15, 25], zoom: 0.8, interactive: false, attributionControl: { compact: true }, renderWorldCopies: false, preserveDrawingBuffer: true } as ConstructorParameters<typeof ml.Map>[0]);
      map.on('load', () => {
        const max = Math.max(...Object.values(values).map(Math.abs), 1e-9);
        for (const [iso3, v] of Object.entries(values)) map!.setFeatureState({ source: 'countries', id: iso3 }, { v: Math.sqrt(Math.abs(v) / max) });
        map!.fitBounds([[-170, -56], [179, 74]], { padding: 4, duration: 0 });
      });
    })();
    return () => { cancelled = true; map?.remove(); };
  }, [values]);
  return <div ref={ref} className="h-[320px] w-full overflow-hidden rounded-xl border border-line print:h-[260px]" role="img" aria-label="Final-state map" />;
}
