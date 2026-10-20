from __future__ import annotations

import datetime as dt


def fnv1a(s: str) -> int:
    h = 0x811C9DC5
    for ch in s.encode():
        h ^= ch
        h = (h * 0x01000193) & 0xFFFFFFFF
    return h


def unit(pid: str, salt: str) -> float:
    """Deterministic value in [0, 1) for an id and salt."""
    return fnv1a(f'{pid}|{salt}') / 4294967296


def clamp01(x: float) -> float:
    return 0.0 if x < 0 else 1.0 if x > 1 else x


def add_days(iso: str, days: int) -> str:
    return (dt.date.fromisoformat(iso) + dt.timedelta(days=days)).isoformat()


def fmt(x: float) -> str:
    a = abs(x)
    if a >= 1e9:
        return f'{x / 1e9:.1f}B'
    if a >= 1e6:
        return f'{x / 1e6:.1f}M'
    if a >= 1e4:
        return f'{x / 1e3:.0f}k'
    if a >= 100:
        return f'{x:,.0f}'
    return f'{x:.2g}' if a < 10 else f'{x:.0f}'
