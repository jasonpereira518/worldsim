'use client';
import { useState } from 'react';
import { useStore, type Layers } from '@/lib/store';

const LAYERS: { key: keyof Layers; label: string }[] = [{ key: 'dots', label: 'People' }, { key: 'institutions', label: 'Institutions' }, { key: 'flows', label: 'Flows' }, { key: 'bubbles', label: 'Bubbles' }, { key: 'live', label: 'Live' }];

export default function LayerPills() {
  const layers = useStore((s) => s.layers);
  const toggleLayer = useStore((s) => s.toggleLayer);
  const meta = useStore((s) => s.meta);
  const choropleth = useStore((s) => s.choropleth);
  const setChoropleth = useStore((s) => s.setChoropleth);
  const current = meta?.layers.find((l) => l.key === choropleth);
  const [legend, setLegend] = useState(false);
  return (
    <div className="absolute left-3 top-3 z-10 flex flex-col items-start gap-2">
      <div className="flex overflow-hidden rounded-full border border-line bg-bg text-[11px]" role="group" aria-label="Layers">
        {LAYERS.map((l) => (
          <button key={l.key} className={`px-2.5 py-1 ${layers[l.key] ? 'bg-ink text-bg' : 'text-muted hover:bg-surface'}`} aria-pressed={layers[l.key]} onClick={() => toggleLayer(l.key)}>{l.label}</button>
        ))}
        <button className="border-l border-line px-2.5 py-1 text-muted hover:bg-surface" aria-expanded={legend} onClick={() => setLegend(!legend)}>Legend</button>
      </div>
      {!!meta?.layers.length && (
        <label className="flex items-center gap-2 rounded-full border border-line bg-bg px-2.5 py-1 text-[11px]">
          <span className="text-muted">Map layer</span>
          <select className="bg-transparent" value={choropleth ?? ''} onChange={(e) => setChoropleth(e.target.value || null)} aria-label="Choropleth layer">
            <option value="">None</option>
            {meta.layers.map((l) => <option key={l.key} value={l.key}>{l.label}</option>)}
          </select>
        </label>
      )}
      {current && (
        <div className="flex items-center gap-2 rounded-full border border-line bg-bg px-2.5 py-1 text-[10px] text-muted" aria-label={`Shading: ${current.label}`}>
          <span>low</span><span aria-hidden className="h-2 w-20 rounded-full" style={{ background: 'linear-gradient(90deg, var(--surface), var(--muted), var(--ink))' }} /><span>high · {current.unit}</span>
        </div>
      )}
      {legend && (
        <dl className="grid grid-cols-[auto_1fr] gap-x-2 gap-y-1 rounded-xl border border-line bg-bg px-3 py-2 text-[11px] text-muted">
          <dt><span className="inline-block h-2.5 w-2.5 rounded-full border border-muted bg-bg" /></dt><dd>unaware (hollow)</dd>
          <dt><span className="inline-block h-2.5 w-2.5 rounded-full bg-gray-2" /></dt><dd>aware</dd>
          <dt><span className="inline-block h-2.5 w-2.5 rounded-full bg-muted" /></dt><dd>reacting</dd>
          <dt><span className="inline-block h-2.5 w-2.5 rounded-full bg-ink" /></dt><dd>affected / adopted</dd>
          <dt><span className="inline-block h-2.5 w-2.5 rounded-full border-2 border-ink bg-bg" /></dt><dd>recovered (ring)</dd>
          <dt><span className="inline-block h-2.5 w-2.5 border-2 border-ink bg-muted" /></dt><dd>opposed</dd>
          <dt><span className="inline-block h-2.5 w-2.5 bg-ink" /></dt><dd>institution (square)</dd>
          <dt><span className="inline-block h-[1px] w-2.5 translate-y-[-3px] bg-ink" /></dt><dd>flow</dd>
          <dt><span className="inline-block h-2.5 w-2.5 rounded-full border-[1.5px] border-ink" /></dt><dd>live earthquake (USGS, ring size = magnitude)</dd>
          <dt /><dd>size = people represented (log)</dd>
        </dl>
      )}
    </div>
  );
}
