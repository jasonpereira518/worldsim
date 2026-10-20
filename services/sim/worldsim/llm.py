"""LLM layer: structured output, caching, retries (SDK), cost tracking and per-run budgets.

Opt-in: set WORLDSIM_LLM=on with credentials the Anthropic SDK can resolve (ANTHROPIC_API_KEY or `ant auth login`).
Off by default so runs never spend money silently; every caller has a deterministic non-LLM path.
LLMs never produce numbers the engine uses: they parse prompts, voice personas and write prose.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger('worldsim.llm')

MAIN_MODEL = os.environ.get('WORLDSIM_MAIN_MODEL', 'claude-opus-5-5')     # parser, key actors, report
FAST_MODEL = os.environ.get('WORLDSIM_FAST_MODEL', 'claude-haiku-5-5')    # routine persona reactions
PRICES = {'claude-opus-5-5': (4.0, 20.0), 'claude-haiku-5-5': (0.10, 0.50), 'claude-sonnet-5-5': (2.0, 10.0)}  # $/MTok in, out
CACHE_DIR = Path(os.environ.get('WORLDSIM_LLM_CACHE', Path(__file__).resolve().parents[1] / '.cache' / 'llm'))
PROMPTS = Path(__file__).parent / 'prompts'


def enabled() -> bool:
    return os.environ.get('WORLDSIM_LLM', 'off').lower() in ('1', 'on', 'true')


def prompt(name: str) -> str:
    """Versioned prompt files live in worldsim/prompts/<name>.md."""
    return (PROMPTS / f'{name}.md').read_text()


@dataclass
class Budget:
    max_calls: int = int(os.environ.get('WORLDSIM_LLM_MAX_CALLS', 60))
    max_usd: float = float(os.environ.get('WORLDSIM_LLM_MAX_USD', 0.50))
    max_calls_per_step: int = 2
    calls: int = 0
    usd: float = 0.0
    cache_hits: int = 0
    refusals: int = 0
    errors: int = 0
    step_calls: dict[int, int] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def allow(self, step: int | None = None) -> bool:
        with self._lock:
            if self.calls >= self.max_calls or self.usd >= self.max_usd:
                return False
            if step is not None and self.step_calls.get(step, 0) >= self.max_calls_per_step:
                return False
            return True

    def record(self, model: str, usage, step: int | None = None) -> None:
        pin, pout = PRICES.get(model, (4.0, 20.0))
        cost = (getattr(usage, 'input_tokens', 0) * pin + getattr(usage, 'output_tokens', 0) * pout) / 1e6
        with self._lock:
            self.calls += 1
            self.usd += cost
            if step is not None:
                self.step_calls[step] = self.step_calls.get(step, 0) + 1

    def report(self) -> dict:
        return {'calls': self.calls, 'usd': round(self.usd, 4), 'cache_hits': self.cache_hits, 'refusals': self.refusals,
                'errors': self.errors, 'max_calls': self.max_calls, 'max_usd': self.max_usd}


_client = None


def client():
    global _client
    if _client is None:
        import anthropic
        _client = anthropic.Anthropic(max_retries=2, timeout=60.0)
    return _client


def _cache_get(key: str):
    f = CACHE_DIR / f'{key}.json'
    return json.loads(f.read_text()) if f.exists() else None


def _cache_put(key: str, value) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    (CACHE_DIR / f'{key}.json').write_text(json.dumps(value))


def structured(system: str, user: str, schema: dict, *, model: str = MAIN_MODEL, budget: Budget | None = None,
               step: int | None = None, max_tokens: int = 4000, effort: str = 'low') -> dict | None:
    """One structured-output call. Returns the parsed object, or None when disabled, over budget, refused or failed."""
    if not enabled():
        return None
    key = hashlib.sha256(json.dumps([model, system, user, schema, effort], sort_keys=True).encode()).hexdigest()[:32]
    hit = _cache_get(key)
    if hit is not None:
        if budget:
            budget.cache_hits += 1
        return hit
    if budget and not budget.allow(step):
        return None
    import anthropic
    kwargs = dict(model=model, max_tokens=max_tokens, system=system, messages=[{'role': 'user', 'content': user}],
                  output_config={'effort': effort, 'format': {'type': 'json_schema', 'schema': schema}})
    try:
        if model.startswith(('claude-opus-5', 'claude-fable-5')):
            # Server-side refusal fallback: routes a declined request to another model inside the same call.
            resp = client().beta.messages.create(**kwargs, betas=['server-side-fallback-2026-07-01'], fallbacks='default')
        else:
            resp = client().messages.create(**kwargs)
    except anthropic.RateLimitError:
        log.warning('LLM rate limited; using deterministic path')
        if budget:
            budget.errors += 1
        return None
    except anthropic.APIStatusError as e:
        log.warning('LLM API error %s; using deterministic path', e.status_code)
        if budget:
            budget.errors += 1
        return None
    except anthropic.APIConnectionError:
        log.warning('LLM connection error; using deterministic path')
        if budget:
            budget.errors += 1
        return None
    if budget:
        budget.record(model, resp.usage, step)
    if resp.stop_reason == 'refusal':
        if budget:
            budget.refusals += 1
        return None
    text = next((b.text for b in resp.content if b.type == 'text'), None)
    if text is None:
        return None
    try:
        out = json.loads(text)
    except json.JSONDecodeError:
        return None
    _cache_put(key, out)
    return out
