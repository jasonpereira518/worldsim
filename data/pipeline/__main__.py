"""Worldsim data pipeline.

  python -m pipeline run [--offline] [--companies N] [--snapshot ID]   refresh every source → data/snapshots/<ID>/
  python -m pipeline status                                             freshness of the latest snapshot (exit 1 if stale)
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timezone

import duckdb

from .fetch import DATA_DIR, Fetcher, SourceUnavailable, now_iso
from .jobs import companies as co, naturalearth as ne, worldbank as wb
from .store import build_snapshot, latest, parquet

# (catalog metadata, job, seconds between live requests). Order matters: later jobs read what earlier ones put in ctx.
JOBS = [
    (ne.ADMIN0, ne.run_admin0, 0),
    (ne.ADMIN1, ne.run_admin1, 0),
    (wb.WDI, wb.run_wdi, 0.2),
    (wb.CLASSIFICATION, wb.run_classification, 0),
    (co.WIKIDATA, co.run_wikidata, 1.0),
    (co.GLEIF, co.run_gleif, 1.0),
    (co.EDGAR, co.run_edgar, 0.12),  # SEC fair-access limit: 10 requests/second
]
CATALOG_KEYS = ['id', 'name', 'source', 'url', 'license', 'confidence', 'fields', 'used_for', 'max_age_days', 'note']


def m0_catalog() -> list[dict]:
    """The M0 populated-places seed is maintained by apps/web/scripts/fetch-places.mjs; list it so the catalog is complete."""
    web = DATA_DIR.parent / 'apps/web/data'
    rows = len(json.loads((web / 'places.json').read_text()))
    return [{**e, 'retrieved': e['retrieved'] + 'T00:00:00Z', 'fetch_status': 'external', 'max_age_days': 1095, 'rows': rows,
             'error': None, 'note': 'Maintained by apps/web/scripts/fetch-places.mjs; still drives persona placement in the mock engine.'}
            for e in json.loads((web / 'catalog.json').read_text())]


def run(args) -> int:
    ctx = {'companies_target': args.companies, 'run_started': now_iso()}
    tables: dict[str, list[dict]] = {}
    catalog, jobs = [], {}
    for meta, job, interval in JOBS:
        fetch = Fetcher(meta['id'], offline=args.offline, min_interval=interval)
        print(f"· {meta['id']} …", end=' ', flush=True)
        entry = {k: meta[k] for k in CATALOG_KEYS}
        try:
            out = job(fetch, ctx)
        except SourceUnavailable as e:
            error = f"{e}{' — last error: ' + fetch.errors[-1].rsplit(': ', 1)[-1] if fetch.errors else ''}"
            catalog.append({**entry, 'as_of': None, 'retrieved': None, 'fetch_status': 'unavailable', 'rows': 0, 'error': error})
            jobs[meta['id']] = {'status': 'unavailable', 'error': error, 'errors': fetch.errors[:20]}
            print(f'UNAVAILABLE ({error})')
            continue
        for name, rows in out['tables'].items():
            tables.setdefault(name, []).extend(rows)
        ctx.update(out.get('ctx', {}))
        n = sum(len(r) for r in out['tables'].values())
        error = '; '.join(fetch.errors[:3])[:500] or None
        catalog.append({**entry, 'as_of': out['as_of'], 'retrieved': fetch.retrieved or ctx['run_started'],
                        'fetch_status': fetch.status, 'rows': n, 'error': error})
        jobs[meta['id']] = {'status': fetch.status, 'retrieved': fetch.retrieved, 'rows': n, 'errors': fetch.errors[:20]}
        print(f'{fetch.status}, {n} rows' + (f' — {len(fetch.errors)} request(s) fell back to cache' if fetch.errors else ''))
    tables['catalog'] = catalog + m0_catalog()
    snapshot_id = args.snapshot or date.today().isoformat()
    path = build_snapshot(snapshot_id, tables, jobs)
    print(f'snapshot {snapshot_id} → {path}')
    return status(args)


def status(args) -> int:
    snap = latest()
    if not snap:
        print('No snapshot yet. Run: python -m pipeline run')
        return 1
    rows = duckdb.sql(f"""SELECT id, fetch_status, as_of, retrieved, max_age_days, rows
                          FROM read_parquet('{parquet(snap, 'catalog')}') ORDER BY id""").fetchall()
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    stale = 0
    print(f'snapshot {snap.name}')
    for id_, st, as_of, retrieved, max_age, n in rows:
        age = (now - retrieved).days if retrieved else None
        is_stale = st in ('cached', 'partial', 'unavailable') or age is None or age > max_age
        stale += is_stale
        print(f"  {'STALE' if is_stale else 'fresh'}  {id_:<26} {st:<11} as_of {as_of}  retrieved {age if age is not None else '—'}d ago  {n} rows")
    return 1 if stale else 0


def main() -> int:
    ap = argparse.ArgumentParser(prog='python -m pipeline', description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)
    r = sub.add_parser('run', help='refresh every source and publish a snapshot')
    r.add_argument('--offline', action='store_true', help='use cached responses only')
    r.add_argument('--companies', type=int, help=f'number of companies (default {co.TARGET})')
    r.add_argument('--snapshot', help='snapshot id (default: today, YYYY-MM-DD)')
    sub.add_parser('status', help='freshness of the latest snapshot')
    args = ap.parse_args()
    return run(args) if args.cmd == 'run' else status(args)


if __name__ == '__main__':
    sys.exit(main())
