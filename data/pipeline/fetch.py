"""HTTP GET with an on-disk cache: live first, last good copy on failure (and the job is marked stale)."""
from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

DATA_DIR = Path(__file__).resolve().parents[1]
CACHE_DIR = DATA_DIR / 'cache'
# SEC asks automated clients to identify themselves; set WORLDSIM_CONTACT to add an email or URL.
USER_AGENT = ' '.join(filter(None, ['Worldsim/0.1 data pipeline', os.environ.get('WORLDSIM_CONTACT')]))


class SourceUnavailable(RuntimeError):
    pass


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


class Fetcher:
    """One per job. Tracks whether every response was live or some came from cache."""

    def __init__(self, job_id: str, offline: bool = False, min_interval: float = 0.0):
        self.job_id = job_id
        self.offline = offline
        self.min_interval = min_interval  # seconds between live requests (rate limits)
        self.status = 'live'
        self.retrieved: str | None = None  # oldest retrieval time among responses used
        self.errors: list[str] = []
        self._last = 0.0

    def _used(self, retrieved: str, status: str) -> None:
        if status == 'cached' and self.status == 'live':  # never downgrade 'partial'
            self.status = 'cached'
        if self.retrieved is None or retrieved < self.retrieved:
            self.retrieved = retrieved

    def _get(self, url: str, headers: dict[str, str], body: bytes | None) -> Any:
        """Live request with 4 attempts on 429/5xx/network errors; 429 waits for Retry-After (≤ 2 min). None on 404."""
        for attempt in range(4):
            wait = self.min_interval - (time.monotonic() - self._last)
            if wait > 0:
                time.sleep(wait)
            self._last = time.monotonic()
            req = urllib.request.Request(url, data=body, headers={'User-Agent': USER_AGENT, 'Accept': 'application/json', **headers})
            backoff = 2 ** (attempt + 1)
            try:
                with urllib.request.urlopen(req, timeout=120) as r:
                    return json.load(r)
            except urllib.error.HTTPError as e:
                if e.code == 404:
                    return None
                if (e.code != 429 and e.code < 500) or attempt == 3:
                    raise
                if e.code == 429:
                    retry_after = e.headers.get('Retry-After', '')
                    backoff = min(int(retry_after) if retry_after.isdigit() else 61, 120)
            except (urllib.error.URLError, TimeoutError, ConnectionError):
                if attempt == 3:
                    raise
            time.sleep(backoff)
        raise AssertionError('unreachable')

    def json(self, url: str, *, headers: dict[str, str] | None = None, body: bytes | None = None,
             transform: Callable[[Any], Any] | None = None) -> Any:
        """GET (or POST `body`) url as JSON. `transform` shrinks the payload before it is cached (e.g. EDGAR company facts)."""
        key = url.encode() + (body or b'')
        path = CACHE_DIR / self.job_id / (hashlib.sha1(key).hexdigest() + '.json')
        if not self.offline:
            try:
                payload = self._get(url, headers or {}, body)
                if transform and payload is not None:
                    payload = transform(payload)
                retrieved = now_iso()
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps({'url': url, 'retrieved': retrieved, 'payload': payload}))
                self._used(retrieved, 'live')
                return payload
            except (OSError, ValueError) as e:  # URLError, HTTPError, timeouts and bad JSON all land here
                self.errors.append(f'{url}: {e}')
        if path.exists():
            cached = json.loads(path.read_text())
            self._used(cached['retrieved'], 'cached')
            return cached['payload']
        raise SourceUnavailable(f'{self.job_id}: no live response and no cached copy for {url}')
