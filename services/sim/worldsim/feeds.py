"""Real-time feeds with provenance. Each feed is cached on disk; when a fetch fails the cached copy is served and
flagged stale. Nothing is synthesized when a feed has never been fetched."""
from __future__ import annotations

import datetime as dt
import json
import os
import time
from pathlib import Path

import httpx

CACHE = Path(os.environ.get('WORLDSIM_FEEDS_CACHE', Path(__file__).resolve().parents[1] / '.cache' / 'feeds'))
TTL_S = 600
UA = {'User-Agent': 'Worldsim/0.2 (research simulator)'}

FEEDS = {
    'usgs_quakes': {'name': 'USGS significant earthquakes, past 7 days', 'url': 'https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/significant_week.geojson',
                    'license': 'Public domain (USGS)', 'publisher': 'U.S. Geological Survey'},
    'usgs_m45': {'name': 'USGS M4.5+ earthquakes, past day', 'url': 'https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/4.5_day.geojson',
                 'license': 'Public domain (USGS)', 'publisher': 'U.S. Geological Survey'},
    'who_don': {'name': 'WHO Disease Outbreak News', 'url': 'https://www.who.int/api/news/diseaseoutbreaknews?$orderby=PublicationDate%20desc&$top=10',
                'license': 'WHO terms of use (attribution)', 'publisher': 'World Health Organization'},
}


def _parse(key: str, payload) -> list[dict]:
    if key.startswith('usgs'):
        out = []
        for f in payload.get('features', []):
            p, (lon, lat, depth) = f['properties'], f['geometry']['coordinates'][:3]
            out.append({'id': f['id'], 'title': p.get('title'), 'magnitude': p.get('mag'), 'place': p.get('place'), 'time': dt.datetime.fromtimestamp(p['time'] / 1000, dt.UTC).isoformat(timespec='minutes'),
                        'lat': lat, 'lon': lon, 'depth_km': depth, 'url': p.get('url'), 'alert': p.get('alert'),
                        'prompt': f'A magnitude {p.get("mag")} earthquake hits {(p.get("place") or "").split(" of ")[-1]}'})
        return out
    if key == 'who_don':
        return [{'id': str(v.get('Id') or v.get('UrlName')), 'title': v.get('Title') or v.get('OverrideTitle'), 'time': v.get('PublicationDate'),
                 'url': f'https://www.who.int/emergencies/disease-outbreak-news/item/{v.get("UrlName")}' if v.get('UrlName') else None,
                 'prompt': (v.get('Title') or '').split(' - ')[0][:200]} for v in payload.get('value', [])]
    return []


def get(key: str, client: httpx.Client | None = None) -> dict:
    meta = FEEDS[key]
    f = CACHE / f'{key}.json'
    cached = json.loads(f.read_text()) if f.exists() else None
    if cached and time.time() - cached['fetched_ts'] < TTL_S:
        return {**cached['entry'], 'status': 'live'}
    try:
        c = client or httpx.Client(timeout=10, headers=UA, follow_redirects=True)
        r = c.get(meta['url'])
        r.raise_for_status()
        items = _parse(key, r.json())
        entry = {'id': key, **meta, 'retrieved': dt.datetime.now(dt.UTC).isoformat(timespec='seconds'), 'items': items, 'error': None}
        CACHE.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps({'fetched_ts': time.time(), 'entry': entry}))
        return {**entry, 'status': 'live'}
    except Exception as e:  # network, HTTP, or schema change: serve the last good copy, flagged
        if cached:
            return {**cached['entry'], 'status': 'stale', 'error': f'{type(e).__name__}: {e}'[:200]}
        return {'id': key, **meta, 'retrieved': None, 'items': [], 'status': 'unavailable', 'error': f'{type(e).__name__}: {e}'[:200]}


def live() -> dict:
    return {'feeds': [get(k) for k in FEEDS], 'as_of': dt.datetime.now(dt.UTC).isoformat(timespec='seconds')}
