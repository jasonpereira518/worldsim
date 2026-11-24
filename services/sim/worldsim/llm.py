"""LLM layer: structured output, tool-use loops, caching, retries (SDK), cost tracking and per-run budgets.

Opt-in: set WORLDSIM_LLM=on with credentials the Anthropic SDK can resolve (ANTHROPIC_API_KEY or `ant auth login`).
Off by default so runs never spend money silently; every caller has a deterministic non-LLM path.
LLMs choose and explain; numbers the engine uses come from data or from priors whose ranges are defined in code
(an agent may narrow a range, never widen it; see agents.py).
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

log = logging.getLogger('worldsim.llm')

MAIN_MODEL = os.environ.get('WORLDSIM_MAIN_MODEL', 'claude-opus-5-5')     # intake, scale assessor, reporter
MID_MODEL = os.environ.get('WORLDSIM_MID_MODEL', 'claude-sonnet-5-5')     # calibrator, actors, critic, institutional voices
FAST_MODEL = os.environ.get('WORLDSIM_FAST_MODEL', 'claude-haiku-5-5')    # crowds, routine persona reactions
# $/MTok: input, output, cache read (cache writes bill at 1.25× input)
PRICES = {'claude-opus-5-5': (4.0, 20.0, 0.20), 'claude-sonnet-5-5': (2.0, 10.0, 0.20), 'claude-haiku-5-5': (0.10, 0.50, 0.01)}
FALLBACK_PREFIXES = ('claude-opus-5', 'claude-fable-5', 'claude-sonnet-5-5')  # server-side refusal fallback (Claude API)
CACHE_DIR = Path(os.environ.get('WORLDSIM_LLM_CACHE', Path(__file__).resolve().parents[1] / '.cache' / 'llm'))
PROMPTS = Path(__file__).parent / 'prompts'


def enabled() -> bool:
    return os.environ.get('WORLDSIM_LLM', 'off').lower() in ('1', 'on', 'true')


def prompt(name: str) -> str:
    """Versioned prompt files live in worldsim/prompts/<name>.md."""
    return (PROMPTS / f'{name}.md').read_text()


def cost(model: str, usage) -> float:
    pin, pout, pcache = PRICES.get(model, (4.0, 20.0, 0.20))
    g = lambda k: getattr(usage, k, 0) or 0
    return (g('input_tokens') * pin + g('output_tokens') * pout + g('cache_read_input_tokens') * pcache
            + g('cache_creation_input_tokens') * pin * 1.25) / 1e6


_RESERVE = threading.Lock()  # check-and-reserve across a budget and its parents in one step


@dataclass
class Budget:
    """Spend caps for one run, or for one agent role inside a run (`parent` is then the run budget and is charged too)."""
    max_calls: int = int(os.environ.get('WORLDSIM_LLM_MAX_CALLS', 80))  # voices take up to 60 (engine.VOICE_CALLS), agents up to 18
    max_usd: float = float(os.environ.get('WORLDSIM_LLM_MAX_USD', 1.00))
    max_calls_per_step: int = 2
    calls: int = 0
    usd: float = 0.0
    cache_hits: int = 0
    refusals: int = 0
    errors: int = 0
    step_calls: dict[int, int] = field(default_factory=dict)
    parent: Budget | None = field(default=None, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def child(self, max_usd: float, max_calls: int | None = None) -> Budget:
        return Budget(max_calls=max_calls or self.max_calls, max_usd=max_usd, parent=self)

    def allow(self, step: int | None = None) -> bool:
        """Reserve one call on this budget and every parent, or False when any cap is reached. The call is counted here,
        before it is made, so concurrent callers (persona voices) cannot overshoot max_calls; dollars are charged in
        record() once the usage is known."""
        with _RESERVE:
            chain, b = [], self
            while b:
                chain.append(b)
                b = b.parent
            if any(x.calls >= x.max_calls or x.usd >= x.max_usd for x in chain):
                return False
            if step is not None and self.step_calls.get(step, 0) >= self.max_calls_per_step:
                return False
            for x in chain:
                x.calls += 1
            if step is not None:
                self.step_calls[step] = self.step_calls.get(step, 0) + 1
        return True

    def record(self, model: str, usage, step: int | None = None) -> None:
        c = cost(model, usage)
        with self._lock:
            self.usd += c
        if self.parent:
            self.parent.record(model, usage)

    def report(self) -> dict:
        return {'calls': self.calls, 'usd': round(self.usd, 4), 'cache_hits': self.cache_hits, 'refusals': self.refusals,
                'errors': self.errors, 'max_calls': self.max_calls, 'max_usd': self.max_usd}


_client = None


def client():
    global _client
    if _client is None:
        import anthropic
        _client = anthropic.Anthropic(max_retries=2, timeout=120.0)
    return _client


def _cache_get(key: str):
    f = CACHE_DIR / f'{key}.json'
    return json.loads(f.read_text()) if f.exists() else None


def _cache_put(key: str, value) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    (CACHE_DIR / f'{key}.json').write_text(json.dumps(value))


def _create(model: str, kwargs: dict, budget: Budget | None):
    """One Messages API call; None (and an error count) on rate limits, API errors and connection failures."""
    import anthropic
    try:
        if model.startswith(FALLBACK_PREFIXES):
            # Server-side refusal fallback: routes a declined request to another model inside the same call.
            return client().beta.messages.create(**kwargs, betas=['server-side-fallback-2026-07-01'], fallbacks='default')
        return client().messages.create(**kwargs)
    except (anthropic.RateLimitError, anthropic.APIStatusError, anthropic.APIConnectionError) as e:
        log.warning('LLM call failed (%s); using deterministic path', type(e).__name__)
        if budget:
            budget.errors += 1
        return None


def agent(system: str, user: str, schema: dict, tools: list[dict] | None = None, *, model: str = MAIN_MODEL, effort: str = 'low',
          budget: Budget | None = None, step: int | None = None, max_turns: int = 4, max_tokens: int = 8000,
          log_fn: Callable[[dict], None] | None = None) -> dict | None:
    """Tool-use loop that ends in a JSON-schema answer. `tools`: [{name, description, input_schema, fn}], read-only.

    Strict tools and output_config.format go in the same request; tool_choice stays auto (forcing a tool is a 400 on
    Opus/Sonnet 5.5) and the last allowed turn sends tool_choice none, so the model must answer. The assistant content is
    appended unchanged (append-only history) and all tool results of a turn go back in one user message.
    Returns the parsed object, or None when disabled, over budget, refused, failed or out of turns."""
    if not enabled():
        return None
    defs = sorted(({'name': t['name'], 'description': t['description'], 'input_schema': t['input_schema'], 'strict': True}
                   for t in tools or []), key=lambda d: d['name'])
    key = hashlib.sha256(json.dumps([model, system, user, schema, effort, defs], sort_keys=True).encode()).hexdigest()[:32]
    hit = _cache_get(key)
    if hit is not None:
        if budget:
            budget.cache_hits += 1
        return hit
    fns = {t['name']: t['fn'] for t in tools or []}
    messages: list[dict] = [{'role': 'user', 'content': user}]
    for turn in range(max_turns):
        if budget and not budget.allow(step):
            return None
        kwargs = dict(model=model, max_tokens=max_tokens, system=system, messages=messages, cache_control={'type': 'ephemeral'},
                      output_config={'effort': effort, 'format': {'type': 'json_schema', 'schema': schema}})
        if defs:
            kwargs['tools'] = defs
            kwargs['tool_choice'] = {'type': 'none'} if turn == max_turns - 1 else {'type': 'auto'}
        resp = _create(model, kwargs, budget)
        if resp is None:
            return None
        if budget:
            budget.record(model, resp.usage, step)
        if log_fn:
            log_fn({'turn': turn, 'model': model, 'stop': resp.stop_reason, 'usd': round(cost(model, resp.usage), 5)})
        if resp.stop_reason == 'refusal':
            if budget:
                budget.refusals += 1
            return None
        uses = [b for b in resp.content if b.type == 'tool_use']
        if resp.stop_reason == 'tool_use' and uses:
            messages.append({'role': 'assistant', 'content': resp.content})
            results = []
            for b in uses:
                try:
                    out = json.dumps(fns[b.name](**b.input), sort_keys=True, default=str)
                    results.append({'type': 'tool_result', 'tool_use_id': b.id, 'content': out})
                except Exception as e:  # reported to the model, which can correct its call
                    results.append({'type': 'tool_result', 'tool_use_id': b.id, 'content': f'{type(e).__name__}: {e}', 'is_error': True})
            messages.append({'role': 'user', 'content': results})
            continue
        text = next((b.text for b in resp.content if b.type == 'text'), None)
        try:
            out = json.loads(text) if text else None
        except json.JSONDecodeError:
            out = None
        if out is not None:
            _cache_put(key, out)
        return out
    return None


def structured(system: str, user: str, schema: dict, *, model: str = MAIN_MODEL, budget: Budget | None = None,
               step: int | None = None, max_tokens: int = 4000, effort: str = 'low') -> dict | None:
    """One structured-output call. Returns the parsed object, or None when disabled, over budget, refused or failed."""
    return agent(system, user, schema, None, model=model, effort=effort, budget=budget, step=step, max_turns=1, max_tokens=max_tokens)
