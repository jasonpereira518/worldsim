"""Loader: job rows → DuckDB (schema.sql enforces the contract) → Parquet snapshot under data/snapshots/<id>/."""
from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path

import duckdb

from .fetch import DATA_DIR, now_iso

SNAPSHOTS_DIR = DATA_DIR / 'snapshots'
SCHEMA = (Path(__file__).parent / 'schema.sql').read_text()


def load(con: duckdb.DuckDBPyConnection, table: str, rows: list[dict]) -> None:
    """Insert dict rows by column name. NDJSON + read_json is ~100x faster than executemany for 300k rows."""
    if not rows:
        return
    with tempfile.NamedTemporaryFile('w', suffix='.ndjson', delete=False) as f:
        for r in rows:
            f.write(json.dumps(r) + '\n')
    try:
        types = {c: t for c, t, *_ in con.execute(f'DESCRIBE {table}').fetchall()}
        spec = '{' + ', '.join(f"'{c}': '{t}'" for c, t in types.items()) + '}'
        con.execute(
            f"INSERT INTO {table} BY NAME SELECT * FROM read_json(?, format='newline_delimited', columns={spec}, maximum_object_size=268435456)",
            [f.name],
        )
    finally:
        Path(f.name).unlink()


def build_snapshot(snapshot_id: str, tables: dict[str, list[dict]], jobs: dict, root: Path = SNAPSHOTS_DIR) -> Path:
    """Validate every row against schema.sql, then publish atomically and point LATEST at it."""
    con = duckdb.connect()
    con.execute(SCHEMA)
    for name, rows in tables.items():
        try:
            load(con, name, rows)
        except duckdb.Error as e:
            raise ValueError(f'{name}: rows violate the data contract: {e}') from e
    root.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f'.{snapshot_id}-', dir=root))
    names = [r[0] for r in con.execute('SHOW TABLES').fetchall()]
    for name in names:
        con.execute(f"COPY {name} TO '{staging / (name + '.parquet')}' (FORMAT parquet, COMPRESSION zstd)")
    manifest = {
        'snapshot_id': snapshot_id,
        'created': now_iso(),
        'tables': {n: con.execute(f'SELECT count(*) FROM {n}').fetchone()[0] for n in names},
        'jobs': jobs,
    }
    (staging / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    final = root / snapshot_id
    if final.exists():
        shutil.rmtree(final)
    staging.rename(final)
    (root / 'LATEST').write_text(snapshot_id + '\n')
    return final


def latest(root: Path = SNAPSHOTS_DIR) -> Path | None:
    p = root / 'LATEST'
    return root / p.read_text().strip() if p.exists() else None


def parquet(snapshot: Path, table: str) -> str:
    """Path for read_parquet(). Relative, because DuckDB treats `*` as a glob and this repo's path contains `**`."""
    return os.path.relpath(snapshot / f'{table}.parquet')
