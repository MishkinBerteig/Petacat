"""FastAPI router for the swarm: one problem over many seeds, on every core.

``POST /api/swarm`` runs a problem (and, for justification, an answer) over a set of seeds
on the warm process pool in ``server.parallel.swarm`` and returns the **answer
distribution**, the per-run outcomes and the telemetry.  Every run is byte-for-byte the
serial run with the same seed, so the distribution is the one a serial loop would have
produced, just N-cores times sooner.

Nothing is persisted (Fast-mode semantics): no Run row, no Trace, no Episodic Memory is
touched, and no database session is required -- the route works with Postgres stopped, as
Fast Run does.  The configuration the runs execute under is the run service's current
metadata (``RunService.meta``), which includes administrator edits adopted at the last
Run created; a changed configuration re-initialises the workers (``Swarm`` keys them by
``config_hash``).

The parallel subsystem is a detachable plugin.  This module imports it guardedly, and with
``server/parallel/`` absent both routes answer **503** with an explanation instead of the
application failing to start.
"""

from __future__ import annotations

import asyncio
import time
from collections import Counter
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from server.api.runs import get_run_service
from server.engine import hardware
from server.engine.numeric import available_backends
from server.engine.parameters import UnknownParameter, validate_overrides

try:
    from server import parallel as _parallel
    from server.parallel import qos as _qos
    from server.parallel import swarm as _swarm
except ImportError:  # the plugin has been detached
    _parallel = _qos = _swarm = None

router = APIRouter(prefix="/api/swarm", tags=["swarm"])

#: Guard rails on one request.  A request holds the pool for as long as it runs.
MAX_RUNS_PER_REQUEST = 20_000
MAX_STEPS_LIMIT = 200_000


def _require_plugin():
    if _swarm is None:
        raise HTTPException(
            503,
            "The parallel subsystem (server/parallel/) is not installed in this build, so "
            "the swarm is unavailable. Petacat itself runs unchanged; use POST /api/runs "
            "for serial runs.",
        )
    return _swarm


class SwarmRequest(BaseModel):
    initial: str
    modified: str
    target: str
    #: Set for justification mode (``init_mcat(answer=...)``); ``None`` is discovery.
    answer: str | None = None
    #: Explicit seeds, or ``count`` seeds starting at ``seed_start``.
    seeds: list[int] | None = None
    count: int | None = Field(default=None, ge=1)
    seed_start: int = 1
    max_steps: int = Field(default=20_000, ge=1, le=MAX_STEPS_LIMIT)
    #: Per-run parameter overrides, validated like ``POST /api/runs``'s.
    parameters: dict[str, Any] | None = None
    #: Numeric backend for the runs.  Omitted takes the swarm's default (a float64 CPU
    #: backend, bit-identical to a serial run).  ``mlx`` is accepted and is much slower.
    backend: str | None = None
    #: Return one entry per run.  Off gives the distribution and telemetry only.
    include_runs: bool = True


class SwarmRunOutcome(BaseModel):
    seed: int
    status: str
    answer: str
    answers: list[str]
    codelets: int
    seconds: float
    stopping_state: str
    temperature: float
    answer_quality: float | None
    error: str | None = None


class DistributionEntry(BaseModel):
    #: The stopping state's answer, or ``*NONE*`` (halted/stopped with none).
    answer: str
    count: int
    fraction: float
    mean_quality: float | None


class SwarmTelemetry(BaseModel):
    workers: int
    runs: int
    seconds: float
    runs_per_second: float
    codelets: int
    codelets_per_second: float
    backend: str
    config_hash: str
    errors: int


class SwarmResponse(BaseModel):
    distribution: list[DistributionEntry]
    statuses: dict[str, int]
    runs: list[SwarmRunOutcome] | None
    telemetry: SwarmTelemetry


class SwarmStatusResponse(BaseModel):
    available: bool
    reason: str | None = None
    started: bool = False
    workers: int = 0
    start_method: str | None = None
    default_backend: str | None = None
    config_hash: str | None = None
    inflight_jobs: int = 0
    tasks_run: int = 0
    startup_seconds: float | None = None
    qos: bool = False
    #: Registered numeric backends whose dependency is importable here.
    backends: list[str] = []
    executors: list[str] = []
    core_tiers: dict | None = None
    limits: dict[str, int] = {}


@router.get("", response_model=SwarmStatusResponse)
async def swarm_status() -> SwarmStatusResponse:
    """Pool status and capabilities.  Never starts the pool."""
    if _swarm is None:
        return SwarmStatusResponse(
            available=False,
            reason="The parallel subsystem (server/parallel/) is not installed.",
        )
    status = _swarm.default_swarm_status()
    tiers = await asyncio.to_thread(_qos.describe_core_tiers)
    return SwarmStatusResponse(
        available=True,
        started=status["started"],
        workers=status["workers"],
        start_method=status["start_method"],
        default_backend=status["default_backend"],
        config_hash=status["config_hash"],
        inflight_jobs=status["inflight_jobs"],
        tasks_run=status["tasks_run"],
        startup_seconds=status["startup_seconds"],
        qos=status["qos"],
        backends=[*available_backends(), "off"],
        executors=["serial", *_parallel.executor_names()],
        core_tiers=tiers.as_dict(),
        limits={
            "max_runs_per_request": MAX_RUNS_PER_REQUEST,
            "max_steps": MAX_STEPS_LIMIT,
            "population_workers": hardware.population_worker_count(),
        },
    )


def _seeds(req: SwarmRequest) -> list[int]:
    if req.seeds:
        seeds = list(req.seeds)
    elif req.count:
        seeds = [req.seed_start + i for i in range(req.count)]
    else:
        raise HTTPException(422, "give either 'seeds' or 'count' (with optional 'seed_start')")
    if len(seeds) > MAX_RUNS_PER_REQUEST:
        raise HTTPException(
            422, f"at most {MAX_RUNS_PER_REQUEST} runs per request, got {len(seeds)}"
        )
    return seeds


@router.post("", response_model=SwarmResponse)
async def run_swarm(req: SwarmRequest) -> SwarmResponse:
    """Run the problem over the seeds on every core; persist nothing."""
    swarm_module = _require_plugin()
    seeds = _seeds(req)
    try:
        overrides = validate_overrides(req.parameters)
    except (UnknownParameter, ValueError) as exc:
        raise HTTPException(400, str(exc)) from exc
    backend = req.backend
    if backend is not None and backend not in {*available_backends(), "off"}:
        raise HTTPException(
            400,
            f"numeric backend {backend!r} is not available here; "
            f"choose from {[*available_backends(), 'off']}",
        )

    # The run service's current metadata: what a Run created now would execute under.
    meta = get_run_service().meta
    swarm = swarm_module.default_swarm()
    tasks = [
        swarm_module.RunTask(
            req.initial, req.modified, req.target, req.answer, seed, req.max_steps,
            parameters=overrides or None, backend=backend,
        )
        for seed in seeds
    ]

    started = time.perf_counter()
    outcomes = await asyncio.to_thread(swarm.map, tasks, meta)
    seconds = time.perf_counter() - started

    by_answer: Counter[str] = Counter()
    quality: dict[str, list[float]] = {}
    for o in outcomes:
        key = o.answer if o.status == "answer_found" and o.answer else "*NONE*"
        by_answer[key] += 1
        if o.answer_quality is not None and key != "*NONE*":
            quality.setdefault(key, []).append(o.answer_quality)
    total = len(outcomes)
    distribution = [
        DistributionEntry(
            answer=answer, count=n, fraction=n / total,
            mean_quality=(sum(quality[answer]) / len(quality[answer])) if answer in quality else None,
        )
        for answer, n in by_answer.most_common()
    ]
    codelets = sum(o.codelets for o in outcomes)
    return SwarmResponse(
        distribution=distribution,
        statuses=dict(Counter(o.status for o in outcomes)),
        runs=(
            [
                SwarmRunOutcome(
                    seed=o.seed, status=o.status, answer=o.answer, answers=o.answers,
                    codelets=o.codelets, seconds=round(o.seconds, 4),
                    stopping_state=o.stopping_state, temperature=o.temperature,
                    answer_quality=o.answer_quality, error=o.error,
                )
                for o in outcomes
            ]
            if req.include_runs
            else None
        ),
        telemetry=SwarmTelemetry(
            workers=swarm.workers,
            runs=total,
            seconds=round(seconds, 4),
            runs_per_second=round(total / seconds, 2) if seconds else 0.0,
            codelets=codelets,
            codelets_per_second=round(codelets / seconds, 1) if seconds else 0.0,
            backend=backend or swarm.backend,
            config_hash=swarm_module.config_hash(meta),
            errors=sum(1 for o in outcomes if o.error),
        ),
    )
