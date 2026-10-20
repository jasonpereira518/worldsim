'use client';
import { useEffect, useState } from 'react';
import { useStore } from '@/lib/store';
import type { DataCatalogEntry } from '@/lib/sim/types';

const ORDER = { unavailable: 0, stale: 1, fresh: 2 } as const;

/** Freshness is shown by fill, never hue: stale and unavailable are solid ink, fresh is a hairline outline. */
function Badge({ e }: { e: DataCatalogEntry }) {
  const label = e.freshness === 'fresh' ? (e.fetch_status === 'external' ? 'external' : 'fresh') : e.freshness;
  return <span className={`shrink-0 rounded-full px-1.5 py-px text-[10px] uppercase tracking-wide ${e.freshness === 'fresh' ? 'border border-line text-muted' : 'bg-ink text-bg'}`}>{label}</span>;
}

function Entry({ e }: { e: DataCatalogEntry }) {
  return (
    <li className="border-t border-line py-2.5">
      <div className="flex items-start gap-2">
        <span className="min-w-0 flex-1 font-medium leading-snug">{e.name}</span>
        <Badge e={e} />
      </div>
      <div className="mt-0.5 text-muted">{e.source} · {e.license} · {e.confidence} confidence</div>
      <dl className="mt-1 grid grid-cols-[72px_1fr] gap-x-2 gap-y-0.5">
        <dt className="text-muted">As of</dt><dd className="num">{e.as_of ?? '—'}</dd>
        <dt className="text-muted">Retrieved</dt><dd className="num">{e.retrieved?.slice(0, 10) ?? '—'} <span className="text-muted">· {e.fetch_status}</span></dd>
        <dt className="text-muted">Rows</dt><dd className="num">{e.rows.toLocaleString()} <span className="text-muted">· refresh every {e.max_age_days}d</span></dd>
      </dl>
      {e.stale_reason && <p className="mt-1 border-l-2 border-ink pl-2 font-medium">{e.stale_reason}</p>}
      <details className="mt-1">
        <summary className="cursor-pointer text-muted hover:text-ink">Fields and notes</summary>
        <p className="mt-1"><span className="text-muted">Used for:</span> {e.used_for}</p>
        <p className="mt-1"><span className="text-muted">Fields:</span> {e.fields.join(', ')}</p>
        {e.note && <p className="mt-1 text-muted">{e.note}</p>}
        <a className="num mt-1 block break-all text-muted underline" href={e.url} target="_blank" rel="noreferrer">{e.url}</a>
      </details>
    </li>
  );
}

export default function DataDrawer() {
  const open = useStore((s) => s.dataDrawerOpen);
  const setOpen = useStore((s) => s.setDataDrawerOpen);
  const spec = useStore((s) => s.spec);
  const [catalog, setCatalog] = useState<DataCatalogEntry[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    let live = true;
    fetch('/api/data/catalog')
      .then(async (r) => (r.ok ? r.json() : Promise.reject(new Error((await r.json().catch(() => null))?.error ?? `HTTP ${r.status}`))))
      .then((c: DataCatalogEntry[]) => { if (live) { setCatalog(c); setError(null); } })
      .catch((e: Error) => { if (live) setError(e.message); });
    return () => { live = false; };
  }, [open]);

  if (!open) return null;
  const sorted = catalog && [...catalog].sort((a, b) => ORDER[a.freshness] - ORDER[b.freshness] || a.name.localeCompare(b.name));
  const flagged = catalog?.filter((e) => e.stale).length ?? 0;

  return (
    <aside className="fade-in absolute bottom-[133px] right-0 top-0 z-20 w-[360px] max-w-full overflow-y-auto border-l border-line bg-bg p-4 text-[12px] md:bottom-[89px]" aria-label="Data and assumptions">
      <div className="flex items-start gap-2">
        <div className="min-w-0 flex-1">
          <h2 className="text-[14px] font-medium leading-tight">Data &amp; assumptions</h2>
          {catalog && (
            <div className="text-muted">
              Snapshot <span className="num">{catalog[0]?.snapshot_id}</span> · {catalog.length} sources · {flagged ? <span className="font-medium text-ink">{flagged} stale</span> : 'all fresh'}
            </div>
          )}
        </div>
        <button aria-label="Close" className="rounded-full border border-line px-2 py-0.5 hover:bg-surface" onClick={() => setOpen(false)}>✕</button>
      </div>

      <h3 className="mb-1 mt-4 text-[10px] uppercase tracking-wide text-muted">Sources</h3>
      {error && <p role="alert" className="border-l-2 border-ink pl-2">{error}</p>}
      {!catalog && !error && <p className="text-muted">Loading catalog…</p>}
      {sorted && <ul>{sorted.map((e) => <Entry key={e.id} e={e} />)}</ul>}
      <p className="border-t border-line pt-2 text-muted">Basemap: OpenFreeMap vector tiles (OpenMapTiles schema, © OpenStreetMap contributors, ODbL).</p>

      <h3 className="mb-1 mt-4 text-[10px] uppercase tracking-wide text-muted">Scenario assumptions</h3>
      {!spec && <p className="text-muted">No scenario yet. Assumptions appear here once a simulation starts.</p>}
      {spec && (
        <ul className="space-y-1">
          {spec.assumptions.map((a) => (
            <li key={a.id} className="flex gap-2">
              <span className="min-w-0 flex-1">{a.text}</span>
              <span className="shrink-0 text-muted">{a.origin} · {a.confidence}</span>
            </li>
          ))}
        </ul>
      )}
      <p className="mt-4 text-[10px] text-muted">The simulation still runs the Milestone 0 mock engine; these datasets feed the engine from Milestone 2. Missing values are labeled, never filled in.</p>
    </aside>
  );
}
