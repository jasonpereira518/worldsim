"""HTTP API (docs/ARCHITECTURE.md section 5). The Next.js app proxies /api/runs/* here."""
from __future__ import annotations

import json
import os
import threading
import time
from collections import OrderedDict
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import PlainTextResponse, StreamingResponse
from pydantic import BaseModel, Field

from . import T0, ENGINE_VERSION, llm
from .chat import handle_chat
from .engine import ENSEMBLE, Run, bands, finish, frames, make_config, prepare
from .models import Intervention, RunConfig, ScenarioSpec
from .parse import parse_prompt
from .util import fnv1a
from .world import world

app = FastAPI(title='Worldsim simulation service', version=ENGINE_VERSION)
RUNS_DIR = Path(os.environ.get('WORLDSIM_RUNS', Path(__file__).resolve().parents[1] / 'runs'))
CACHE: OrderedDict[str, Run] = OrderedDict()
LOCK = threading.Lock()
FRAME_DELAY = float(os.environ.get('WORLDSIM_FRAME_DELAY', 0.02))


class CreateRun(BaseModel):
    prompt: str = Field(min_length=1, max_length=500)
    answers: dict[str, str] | None = None
    assumptions: dict[str, float] | None = None  # edited assumption values by id
    seed: int | None = None
    parent_run_id: str | None = None
    branch_at: int | None = None
    interventions: list[Intervention] | None = None
    label: str | None = Field(default=None, max_length=80)


def save_config(cfg: RunConfig, overrides: dict) -> None:
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    (RUNS_DIR / f'{cfg.run_id}.json').write_text(json.dumps({'config': cfg.model_dump(by_alias=True), 'overrides': overrides}, indent=1))


def load_config(run_id: str) -> tuple[RunConfig, dict]:
    f = RUNS_DIR / f'{run_id}.json'
    if not f.exists() or not run_id.replace('_', '').isalnum():
        raise HTTPException(404, 'unknown run')
    d = json.loads(f.read_text())
    return RunConfig.model_validate(d['config']), d.get('overrides', {})


def get_run(run_id: str) -> Run:
    with LOCK:
        if run_id in CACHE:
            CACHE.move_to_end(run_id)
            return CACHE[run_id]
    cfg, overrides = load_config(run_id)
    run = prepare(cfg, overrides)
    with LOCK:
        CACHE[run_id] = run
        while len(CACHE) > 12:
            CACHE.popitem(last=False)
    return run


def create(body: CreateRun) -> RunConfig:
    w = world()
    overrides = dict(body.assumptions or {})
    if body.parent_run_id:
        parent, parent_over = load_config(body.parent_run_id)
        spec = parent.spec.model_copy(deep=True)
        overrides = {**parent_over, **overrides}
        new = list(body.interventions or [])
        if not new and not body.assumptions:
            from .parse import parse_interventions
            new = parse_interventions(body.prompt)
        spec.interventions = spec.interventions + new
        for iv in new:
            if iv.kind == 'price_change' and iv.value is not None:
                base = next((a.value for a in spec.assumptions if a.id == 'price_usd'), None)
                if base:
                    overrides['price_usd'] = float(base) * (1 + iv.value / 100)
            if iv.kind == 'tariff_change' and iv.value is not None:
                overrides['tariff_pct'] = iv.value
        seed = parent.seed if body.seed is None else body.seed
        label = body.label or body.prompt[:80]
    else:
        spec = parse_prompt(body.prompt, w, body.answers)
        seed = body.seed if body.seed is not None else fnv1a(body.prompt + json.dumps(body.answers or {}, sort_keys=True))
        label = body.label
    if overrides.get('horizon_days'):
        spec.horizon_days = int(overrides['horizon_days'])
    for a in spec.assumptions:
        if a.id in overrides:
            a.value, a.origin, a.confidence = overrides[a.id], 'user', 'high'
    run_id = f'run_{int(time.time() * 1000):x}_{seed % 46656:x}'
    cfg = make_config(spec, seed, run_id, w.snapshot_id, body.parent_run_id, body.branch_at, label)
    save_config(cfg, overrides)
    return cfg


@app.get('/health')
def health():
    w = world()
    return {'ok': True, 'engine': ENGINE_VERSION, 't0': T0, 'snapshot': w.snapshot_id, 'data_available': w.available,
            'llm': 'on' if llm.enabled() else 'off', 'ensemble': ENSEMBLE}


@app.post('/runs', status_code=201)
def post_run(body: CreateRun):
    cfg = create(body)
    return {'run_id': cfg.run_id, 'spec': cfg.spec.model_dump(by_alias=True), 'parent_run_id': cfg.parent_run_id}


@app.get('/runs')
def list_runs(limit: int = 30):
    out = []
    for f in sorted(RUNS_DIR.glob('run_*.json'), key=lambda p: p.stat().st_mtime, reverse=True)[:limit]:
        c = json.loads(f.read_text())['config']
        out.append({'run_id': c['run_id'], 'title': c['spec']['title'], 'created_at': c['created_at'], 'parent_run_id': c.get('parent_run_id'),
                    'label': c.get('label'), 'module': c['spec']['module'], 'seed': c['seed']})
    return out


@app.get('/runs/{run_id}')
def get_config(run_id: str):
    cfg, overrides = load_config(run_id)
    return {**cfg.model_dump(by_alias=True), 'overrides': overrides}


def sse(kind: str, data) -> str:
    return f'event: {kind}\ndata: {json.dumps({"type": kind, **data}, separators=(",", ":"), allow_nan=False, default=str)}\n\n'


def clean(o):
    """JSON-safe: NaN/inf → None."""
    import math
    if isinstance(o, float):
        return o if math.isfinite(o) else None
    if isinstance(o, dict):
        return {k: clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [clean(v) for v in o]
    return o


@app.get('/runs/{run_id}/stream')
def stream(run_id: str):
    run = get_run(run_id)

    def gen():
        try:
            yield sse('personas', {'personas': [p.model_dump() for p in run.personas]})
            m = run.module
            yield sse('meta', {'meta': {'run_id': run.config.run_id, 'module': m.name, 'key_metric': m.key_metric, 'key_unit': m.key_unit,
                                        'persona_metric': {'name': m.persona_metric[0], 'unit': m.persona_metric[1]},
                                        'layers': [{'key': k, 'label': l, 'unit': u} for k, l, u in m.layers], 'ensemble_size': ENSEMBLE,
                                        'parent_run_id': run.config.parent_run_id, 'label': run.config.label, 'engine': run.config.engine_version}})
            if not run.ensemble:
                n = ENSEMBLE
                yield sse('progress', {'t': 0, 'total': run.ctx.steps, 'label': f'Running ensemble 0 of {n}'})
                import numpy as np
                from .engine import central, sample_params
                for i in range(n):
                    rng = np.random.default_rng([run.config.seed, i])
                    params = central(run.priors) if i == 0 else sample_params(run.priors, rng)
                    run.params.append(params)
                    run.ensemble.append(run.module.simulate(run.ctx, params, np.random.default_rng([run.config.seed, i, 1]), detail=False))
                    if (i + 1) % 4 == 0 or i + 1 == n:
                        yield sse('progress', {'t': 0, 'total': run.ctx.steps, 'label': f'Running ensemble {i + 1} of {n}'})
                finals = np.array([tr.key[-1] for tr in run.ensemble])
                run.median = int(np.argmin(np.abs(finals - np.median(finals))))
                run.traj = run.module.simulate(run.ctx, run.params[run.median], np.random.default_rng([run.config.seed, run.median, 1]), detail=True)
            replay = bool(run.frames)
            src = run.frames if replay else frames(run)
            done_frames = []
            for f in src:
                done_frames.append(f)
                yield sse('frame', {'frame': clean(f.model_dump(by_alias=True))})
                if f.t % 5 == 0 or f.t == run.ctx.steps:
                    yield sse('progress', {'t': f.t, 'total': run.ctx.steps, 'label': f'Simulating day {f.t * run.ctx.dt} of {run.ctx.steps * run.ctx.dt}'})
                if not replay:
                    time.sleep(FRAME_DELAY)
            if not replay:
                run.frames = done_frames
                yield sse('progress', {'t': run.ctx.steps, 'total': run.ctx.steps, 'label': 'Running sensitivity analysis'})
                finish(run)
            yield sse('summary', {'summary': clean(run.summary.model_dump())})
            yield sse('report', {'report': clean(run.report)})
            yield sse('done', {})
        except Exception as e:  # surfaced to the client; never a silent failure
            import logging
            logging.exception('run %s failed', run_id)
            yield sse('error', {'message': f'{type(e).__name__}: {e}'})

    return StreamingResponse(gen(), media_type='text/event-stream', headers={'Cache-Control': 'no-cache, no-transform', 'X-Accel-Buffering': 'no'})


def completed(run_id: str) -> Run:
    run = get_run(run_id)
    if not run.report:
        from .engine import execute
        execute(run)
    return run


@app.get('/runs/{run_id}/report')
def report_json(run_id: str):
    return clean(completed(run_id).report)


@app.get('/runs/{run_id}/report.md', response_class=PlainTextResponse)
def report_md(run_id: str):
    from .report import to_markdown
    return to_markdown(clean(completed(run_id).report))


class ChatBody(BaseModel):
    message: str = Field(min_length=1, max_length=500)
    t: int | None = None  # playhead when the user asked


@app.post('/runs/{run_id}/chat')
def chat(run_id: str, body: ChatBody):
    return clean(handle_chat(completed(run_id), body.message, body.t, create))


@app.get('/runs/{run_id}/compare/{other_id}')
def compare(run_id: str, other_id: str):
    from .compare import compare_runs
    return clean(compare_runs(completed(run_id), completed(other_id)))


@app.get('/feeds/live')
def feeds_live():
    from .feeds import live
    return live()
