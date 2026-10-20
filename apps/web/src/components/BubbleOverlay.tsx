'use client';
import { useMemo } from 'react';
import type { Map as MLMap } from 'maplibre-gl';
import { BUBBLE_WIDTH, bubbleCap, estimateHeight, layoutBubbles } from '@/lib/map/bubbles';
import { useStore } from '@/lib/store';

const TTL = 6; // steps a bubble stays eligible

export default function BubbleOverlay({ map }: { map: MLMap }) {
  const bubbles = useStore((s) => s.bubbles);
  const personas = useStore((s) => s.personas);
  const personaIndex = useStore((s) => s.personaIndex);
  const playhead = useStore((s) => s.playhead);
  const layers = useStore((s) => s.layers);
  const selectPersona = useStore((s) => s.selectPersona);
  const canvas = map.getCanvas();
  const zoom = map.getZoom();
  const center = map.getCenter();

  const placed = useMemo(() => {
    if (!layers.bubbles) return [];
    const vp = { width: canvas.clientWidth, height: canvas.clientHeight };
    const anchors = [];
    for (let i = bubbles.length - 1; i >= 0; i--) {
      const b = bubbles[i];
      if (b.t > playhead) continue;
      if (b.t < playhead - TTL) break;
      const p = personas[personaIndex[b.persona_id]];
      if (!p || (p.kind === 'people' && !layers.dots) || (p.kind === 'institution' && !layers.institutions)) continue;
      const pt = map.project([p.location.lon, p.location.lat]);
      const age = playhead - b.t;
      anchors.push({ id: b.id, x: pt.x, y: pt.y, w: BUBBLE_WIDTH, h: estimateHeight(b.text) + 14, priority: b.priority * (1 - 0.8 * (age / TTL)) });
    }
    return layoutBubbles(anchors, vp, bubbleCap(zoom)).map((pl) => ({ ...pl, bubble: bubbles.find((b) => b.id === pl.id)! }));
    // center/zoom are read so the layout recomputes on every map move
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [bubbles, personas, personaIndex, playhead, layers, map, canvas.clientWidth, canvas.clientHeight, zoom, center.lng, center.lat]);

  return (
    <div className="pointer-events-none absolute inset-0 overflow-hidden" aria-live="off">
      {placed.map(({ bubble: b, left, top, side }) => {
        const p = personas[personaIndex[b.persona_id]];
        const age = playhead - b.t;
        return (
          <div key={b.id} className="bubble fade-in" data-side={side} style={{ left, top, opacity: age >= TTL - 1 ? 0.5 : age >= TTL - 2 ? 0.75 : 1 }} role="button" tabIndex={0}
            onClick={() => selectPersona(b.persona_id)} onKeyDown={(e) => e.key === 'Enter' && selectPersona(b.persona_id)}>
            <div>{b.text}</div>
            <div className="mt-1 flex items-center gap-1 text-[10px] text-muted">
              <span aria-hidden>{p.kind === 'institution' ? '■' : '●'}</span>
              <span className="truncate">{p.label}</span>
            </div>
            <div className="why">
              <strong className="text-ink">Why:</strong> {b.why.event}. {b.why.metric.replace('_', ' ')} <span className="num">{b.why.before}</span> → <span className="num">{b.why.after}</span> {b.why.unit}.
            </div>
          </div>
        );
      })}
    </div>
  );
}
