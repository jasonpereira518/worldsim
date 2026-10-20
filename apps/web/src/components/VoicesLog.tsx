'use client';
import { useMemo } from 'react';
import { useStore, type Filters } from '@/lib/store';

const sel = 'min-w-0 flex-1 rounded-full border border-line bg-bg px-2 py-0.5 text-[11px]';

export default function VoicesLog() {
  const bubbles = useStore((s) => s.bubbles);
  const personas = useStore((s) => s.personas);
  const personaIndex = useStore((s) => s.personaIndex);
  const playhead = useStore((s) => s.playhead);
  const frames = useStore((s) => s.frames);
  const filters = useStore((s) => s.filters);
  const setFilters = useStore((s) => s.setFilters);
  const selectPersona = useStore((s) => s.selectPersona);
  const requestZoom = useStore((s) => s.requestZoom);

  const countries = useMemo(() => Array.from(new Set(bubbles.map((b) => personas[personaIndex[b.persona_id]]?.location.country_iso3).filter(Boolean))).sort(), [bubbles, personas, personaIndex]);
  const visible = useMemo(() => {
    const out = [];
    for (let i = bubbles.length - 1; i >= 0 && out.length < 300; i--) {
      const b = bubbles[i];
      if (b.t > playhead) continue;
      const p = personas[personaIndex[b.persona_id]];
      if (!p) continue;
      if (filters.country !== 'all' && p.location.country_iso3 !== filters.country) continue;
      if (filters.kind !== 'all' && p.kind !== filters.kind) continue;
      if (filters.sentiment !== 'all' && String(b.sentiment) !== filters.sentiment) continue;
      out.push({ b, p });
    }
    return out;
  }, [bubbles, personas, personaIndex, playhead, filters]);

  const set = (k: keyof Filters) => (e: React.ChangeEvent<HTMLSelectElement>) => setFilters({ [k]: e.target.value } as Partial<Filters>);
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex shrink-0 gap-1 border-b border-line p-2">
        <select className={sel} aria-label="Country" value={filters.country} onChange={set('country')}><option value="all">All countries</option>{countries.map((c) => <option key={c} value={c}>{c}</option>)}</select>
        <select className={sel} aria-label="Persona type" value={filters.kind} onChange={set('kind')}><option value="all">People + institutions</option><option value="people">People</option><option value="institution">Institutions</option></select>
        <select className={sel} aria-label="Sentiment" value={filters.sentiment} onChange={set('sentiment')}><option value="all">Any sentiment</option><option value="1">Positive</option><option value="0">Neutral</option><option value="-1">Negative</option></select>
      </div>
      <ul className="min-h-0 flex-1 divide-y divide-line overflow-y-auto">
        {visible.map(({ b, p }) => (
          <li key={b.id}>
            <button className="w-full px-3 py-2 text-left hover:bg-surface" onClick={() => { selectPersona(p.id); requestZoom([p.location.lon, p.location.lat], 5); }}>
              <div className="text-[12px]">{b.text}</div>
              <div className="mt-0.5 flex items-center gap-2 text-[10px] text-muted">
                <span aria-hidden>{p.kind === 'institution' ? '■' : '●'}</span>
                <span className="truncate">{p.label}</span>
                <span className="num ml-auto shrink-0">{frames[b.t]?.date}</span>
                <span aria-label={b.sentiment > 0 ? 'positive' : b.sentiment < 0 ? 'negative' : 'neutral'}>{b.sentiment > 0 ? '▲' : b.sentiment < 0 ? '▼' : '–'}</span>
              </div>
            </button>
          </li>
        ))}
        {visible.length === 0 && <li className="p-3 text-[12px] text-muted">No voices yet at this point in the timeline.</li>}
      </ul>
    </div>
  );
}
