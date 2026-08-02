"""FastAPI router for run lifecycle endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from server.db import get_session
from server.models.run import Run

router = APIRouter(prefix="/api/runs", tags=["runs"])

# RunService is set at app startup
_run_service = None


def get_run_service():
    if _run_service is None:
        raise HTTPException(500, "RunService not initialized")
    return _run_service


# ------------------------------------------------------------------
# Request / Response models
# ------------------------------------------------------------------


class CreateRunRequest(BaseModel):
    initial: str
    modified: str
    target: str
    answer: str | None = None
    seed: int = 0
    #: Set at creation so the whole run uses it, rather than being applied after
    #: the engine has already been initialised.
    spreading_threshold: int | None = None
    #: Persistence mode — ``fast``, ``normal`` or ``audit``.  A property of this run
    #: rather than a global setting, so a Fast corpus-training population and a Normal
    #: live dialogue can coexist in one process.  ``fast`` touches the database at no
    #: point, including creation, so a Fast Run works with Postgres stopped.
    mode: str = "normal"
    #: Worker threads for free-running execution (WP4.4).  1 — the default — is the
    #: serial loop, which stays the reference mode.  Above 1 the run's codelets execute
    #: across CPU cores with no global barrier; the expected range is unchanged, but a
    #: seed no longer reproduces a run, because execution order is not determined.
    #: Audit refuses anything above 1, since its forward log would not describe the
    #: order things actually happened in.
    #:
    #: 0 asks for this machine's own count — one worker per performance core, which
    #: ``GET /api/system/numeric`` reports under ``derived.workers``.  It is how a
    #: caller says "use the cores you have" without first learning how many there are.
    workers: int = 1
    #: Per-run overrides for the engine's fixed run parameters, by name.  Omitted
    #: parameters keep the global default.  An unknown name is rejected rather than
    #: ignored: ignoring it would produce a Run at the default while the record claimed
    #: the override was applied.
    parameters: dict[str, Any] | None = None


class StepRequest(BaseModel):
    n: int = 1


class RunToCompletionRequest(BaseModel):
    max_steps: int = 0


class RunResponse(BaseModel):
    run_id: int
    mode: str = "normal"
    status: str
    codelet_count: int
    temperature: float
    initial: str
    modified: str
    target: str
    answer: str | None
    #: The answer was supplied for the engine to justify, not discovered by it.
    justify_mode: bool = False
    #: Which Slipnet nodes were allowed to spread; 100 is the original.
    spreading_threshold: int = 100


class RunListItem(RunResponse):
    """A listed run, plus the identity fields only the row carries.

    Separate from ``RunResponse`` rather than folded into it because the two are
    populated from different places: ``RunResponse`` is built from a ``RunInfo``,
    which is assembled from the live runner and knows nothing about hashes, whereas a
    listing reads rows and has them to hand.  Widening ``RunResponse`` would mean
    every single-run endpoint answering ``config_hash: null`` for runs that plainly
    have one, which reads as "no config hash" rather than "not looked up".
    """

    config_hash: str | None = None
    memory_hash: str | None = None


class RunListResponse(BaseModel):
    runs: list[RunListItem]
    total: int
    limit: int
    offset: int


class RunIdentityResponse(BaseModel):
    """What identifies a Run as an experiment, rather than what it is doing.

    Seed and problem say what was asked; ``config_hash`` and ``memory_hash`` say what
    it was asked *of*.  Two Runs with one seed and different hashes are not the same
    experiment, which is why the Review browser shows them — and why a live run needs
    somewhere to show them too, since by the time a reader is in the Review browser
    the run they were watching is over.
    """

    run_id: int
    mode: str
    #: False for a Fast Run.  There is no ``runs`` row, so there is nothing to read
    #: the hashes from and nothing to link a Training Session to.  This is the mode
    #: keeping its promise, not a lookup failure, and the client says so.
    recorded: bool
    seed: int | None = None
    spreading_threshold: int = 100
    config_hash: str | None = None
    memory_hash: str | None = None
    #: The Training Session this Run belongs to — the span between memory clears.
    session_id: int | None = None
    created_at: datetime | None = None


class StepResponse(BaseModel):
    codelet_count: int
    codelet_type: str
    answer_found: bool = False
    answer: str | None = None
    gave_up: bool = False
    #: The run paused at its breakpoint after this codelet, so this is the last entry
    #: of the batch and fewer codelets ran than were asked for.  The breakpoint stays
    #: set and the run's status is ``paused``; a step made while the run is already at
    #: the breakpoint runs no codelets and returns an empty list, and the run's status
    #: reports that pause.
    breakpoint_hit: bool = False


# ------------------------------------------------------------------
# Existing endpoints
# ------------------------------------------------------------------


@router.post("", response_model=RunResponse)
async def create_run(
    req: CreateRunRequest,
    session: AsyncSession = Depends(get_session),
):
    svc = get_run_service()
    try:
        info = await svc.create_run(
            session, req.initial, req.modified, req.target, req.answer, req.seed,
            spreading_threshold=req.spreading_threshold, mode=req.mode,
            workers=req.workers, parameters=req.parameters,
        )
    except ValueError as exc:
        # An unknown mode name. Rejected rather than defaulted: silently giving a Fast
        # Run to someone who asked for Audit would only show up when the record they
        # expected turned out not to exist.
        raise HTTPException(400, str(exc)) from None
    return RunResponse(
        run_id=info.run_id,
        status=info.status,
        codelet_count=info.codelet_count,
        temperature=info.temperature,
        initial=info.initial,
        modified=info.modified,
        target=info.target,
        answer=info.answer,
        justify_mode=info.justify_mode,
        spreading_threshold=info.spreading_threshold,
        mode=info.mode,
    )


@router.get("/{run_id}", response_model=RunResponse)
async def get_run(
    run_id: int,
    session: AsyncSession = Depends(get_session),
):
    svc = get_run_service()
    info = await svc.get_run_info(session, run_id)
    if info is None:
        raise HTTPException(404, f"Run {run_id} not found")
    return RunResponse(
        run_id=info.run_id,
        status=info.status,
        codelet_count=info.codelet_count,
        temperature=info.temperature,
        initial=info.initial,
        modified=info.modified,
        target=info.target,
        answer=info.answer,
        justify_mode=info.justify_mode,
        spreading_threshold=info.spreading_threshold,
        mode=info.mode,
    )


@router.post("/{run_id}/step", response_model=list[StepResponse])
async def step_run(
    run_id: int,
    req: StepRequest,
    session: AsyncSession = Depends(get_session),
):
    svc = get_run_service()
    try:
        batch = await svc.step(session, run_id, req.n)
    except ValueError as e:
        raise HTTPException(404, str(e))
    # The breakpoint stopped the batch after its final codelet, so that entry carries
    # the flag: it is the codelet the run is paused at.
    last = len(batch.results) - 1
    return [
        StepResponse(
            codelet_count=r.codelet_count,
            codelet_type=r.codelet_type,
            answer_found=r.answer_found,
            answer=r.answer,
            gave_up=r.gave_up,
            breakpoint_hit=batch.breakpoint_hit and i == last,
        )
        for i, r in enumerate(batch.results)
    ]


@router.get("/{run_id}/workspace")
async def get_workspace(run_id: int):
    svc = get_run_service()
    state = svc.get_workspace_state(run_id)
    if state is None:
        raise HTTPException(404, f"Run {run_id} not found")
    return state


@router.get("/{run_id}/slipnet")
async def get_slipnet(run_id: int):
    svc = get_run_service()
    state = svc.get_slipnet_state(run_id)
    if state is None:
        raise HTTPException(404, f"Run {run_id} not found")
    return state


@router.get("/{run_id}/coderack")
async def get_coderack(run_id: int):
    svc = get_run_service()
    state = svc.get_coderack_state(run_id)
    if state is None:
        raise HTTPException(404, f"Run {run_id} not found")
    return state


@router.get("/{run_id}/temperature")
async def get_temperature(run_id: int):
    """The temperature and its clamp state, as the engine holds them.

    ``clamped`` is what the gauge's clamped indicator follows, so the indicator
    reports the engine and survives a remount of the display.
    """
    svc = get_run_service()
    state = svc.get_temperature_state(run_id)
    if state is None:
        raise HTTPException(404, f"Run {run_id} not found")
    return {"run_id": run_id, **state}


# ------------------------------------------------------------------
# New endpoints
# ------------------------------------------------------------------


@router.get("", response_model=RunListResponse)
async def list_runs(
    limit: int = 50,
    offset: int = 0,
    session: AsyncSession = Depends(get_session),
):
    """List all runs (paginated).

    Fast Runs are structurally absent: they have no row, so nothing can list them.
    The client explains that where the absence would otherwise look like a bug.
    """
    svc = get_run_service()
    runs, total = await svc.list_runs(session, limit=limit, offset=offset)

    # Mode and the two hashes come from a second query rather than from ``RunInfo``,
    # which does not carry them.  One statement over the ids just returned, so the
    # cost is a single round trip regardless of the page size.
    identity: dict[int, tuple[str, str | None, str | None]] = {}
    if runs:
        rows = await session.execute(
            select(Run.id, Run.mode, Run.config_hash, Run.memory_hash).where(
                Run.id.in_([r.run_id for r in runs])
            )
        )
        identity = {
            row.id: (row.mode or "normal", row.config_hash, row.memory_hash)
            for row in rows
        }

    items = []
    for r in runs:
        # A run listed but absent from the identity query predates the mode column,
        # and "normal" is what it was: the column's server default backfills it.
        mode, config, memory = identity.get(r.run_id, ("normal", None, None))
        items.append(
            RunListItem(
                run_id=r.run_id,
                status=r.status,
                codelet_count=r.codelet_count,
                temperature=r.temperature,
                initial=r.initial,
                modified=r.modified,
                target=r.target,
                answer=r.answer,
                justify_mode=r.justify_mode,
                spreading_threshold=r.spreading_threshold,
                mode=mode,
                config_hash=config,
                memory_hash=memory,
            )
        )

    return RunListResponse(runs=items, total=total, limit=limit, offset=offset)


@router.get("/{run_id}/identity", response_model=RunIdentityResponse)
async def get_run_identity(
    run_id: int,
    session: AsyncSession = Depends(get_session),
):
    """The recorded identity of a run: mode, seed, config hash, memory hash, session.

    Served here rather than from ``/api/review`` because this one is about a run that
    may still be executing.  The review router's contract is that its 404 means
    "nothing was recorded"; this endpoint answers for a Fast Run too, and answers
    ``recorded: false`` rather than 404, because "this run wrote nothing" is a fact
    about it and not an absence of one.
    """
    svc = get_run_service()
    info = await svc.get_run_info(session, run_id)
    if info is None:
        raise HTTPException(404, f"Run {run_id} not found")

    result = await session.execute(select(Run).where(Run.id == run_id))
    row = result.scalar_one_or_none()
    if row is None:
        # A Fast Run: live, observable, and with no row behind it by design.
        return RunIdentityResponse(
            run_id=run_id,
            mode=info.mode,
            recorded=False,
            spreading_threshold=info.spreading_threshold,
        )

    return RunIdentityResponse(
        run_id=row.id,
        mode=row.mode or "normal",
        recorded=True,
        seed=row.seed,
        spreading_threshold=(
            100 if row.spreading_threshold is None else int(row.spreading_threshold)
        ),
        config_hash=row.config_hash,
        memory_hash=row.memory_hash,
        session_id=row.session_id,
        created_at=row.created_at,
    )


@router.get("/parameters/catalogue")
async def get_parameter_catalogue():
    """Every settable run parameter: kind, bounds, current default, and what it does.

    Served rather than duplicated in the client, because the bounds are the same ones
    the API validates against and two copies would drift — a control that lets you set a
    value the server rejects is worse than no control.

    Placed above ``/{run_id}/...`` so ``parameters`` is not parsed as a run id.
    """
    from server.engine.parameters import describe_parameters

    svc = get_run_service()
    return {"parameters": describe_parameters(svc.meta)}


@router.get("/{run_id}/parameters")
async def get_run_parameters(
    run_id: int, session: AsyncSession = Depends(get_session),
):
    """What this Run was: the fixed parameters it ran under, and what they produced.

    Both halves in one response because reading a Run needs both, and separating them
    invites the mistake of showing derived values as though they were settings. The
    ``fixed`` half is the *resolved* set — every parameter, not only the overridden ones
    — so it is self-contained even if the global defaults change afterwards.
    """
    from server.engine.parameters import RUN_PARAMETERS, resolved_parameters

    svc = get_run_service()
    runner = svc._runners.get(run_id)

    stored: dict | None = None
    row = None
    if run_id > 0:
        result = await session.execute(select(Run).where(Run.id == run_id))
        row = result.scalar_one_or_none()
        if row is not None:
            stored = row.parameters

    if stored is None and runner is not None and runner.ctx is not None:
        # A Fast Run has no row, and a Run created before this column existed has a null
        # one; the live runner is then the only account of what it is executing under.
        stored = resolved_parameters(runner.ctx.meta)
    if stored is None:
        raise HTTPException(404, f"No parameter record for run {run_id}")

    defaults = {p.name: svc.meta.get_param(p.name) for p in RUN_PARAMETERS}
    overridden = sorted(n for n, v in stored.items() if defaults.get(n) != v)

    derived: dict = {
        "mode": (row.mode if row is not None else svc._modes.get(run_id, "fast")),
        "workers": svc._workers.get(run_id, 1),
        "config_hash": row.config_hash if row is not None else None,
        "memory_hash": row.memory_hash if row is not None else None,
        "session_id": row.session_id if row is not None else None,
        "seed": row.seed if row is not None else None,
        "recorded": row is not None,
    }

    if runner is not None and runner.ctx is not None:
        ctx = runner.ctx
        coderack = ctx.coderack
        shards = getattr(coderack, "num_shards", 1)
        derived.update(
            {
                "codelet_count": ctx.codelet_count,
                "temperature": round(ctx.temperature.value, 2),
                "status": runner.status,
                "justify_mode": ctx.justify_mode,
                "slipnet_nodes": len(ctx.slipnet.nodes),
                "coderack_shards": shards,
                # Sharding divides the rack's capacity rather than replicating it, and
                # a shard below the floor is too small for the jootsing sequence to
                # complete — so the per-shard figure is the one worth seeing.
                "coderack_capacity_per_shard": (
                    coderack._racks[0].max_size if shards > 1 else coderack.max_size
                ),
                "staleness_delay": ctx.staleness_delay,
            }
        )
        telemetry = svc._free_run_telemetry.get(run_id)
        if telemetry is not None:
            derived["free_running"] = telemetry

    try:
        from server.engine.numeric.backend import select_backend

        backend = select_backend(
            len(runner.ctx.slipnet.nodes) if runner and runner.ctx else 59
        )
        derived["numeric_backend"] = getattr(backend, "name", None) if backend else None
        derived["numeric_device"] = (
            str(getattr(backend, "device", "")) if backend else None
        )
    except Exception:  # pragma: no cover - the substrate is optional
        derived["numeric_backend"] = None

    return {
        "run_id": run_id,
        "fixed": stored,
        "overridden": overridden,
        "defaults": defaults,
        "derived": derived,
    }


@router.get("/{run_id}/telemetry")
async def get_run_telemetry(run_id: int):
    """Free-running telemetry for a run, if it ran free-running.

    Reported rather than inferred, because the interesting figures — the conflict rate
    and how the work actually divided between workers — cannot be reconstructed from
    the run's record afterwards. A free-running run is one draw, and this is the only
    account of how it was taken.
    """
    svc = get_run_service()
    telemetry = svc._free_run_telemetry.get(run_id)
    if telemetry is None:
        return {"run_id": run_id, "free_running": False}
    return {"run_id": run_id, "free_running": True, **telemetry}


@router.post("/{run_id}/run", response_model=RunResponse)
async def run_to_completion(
    run_id: int,
    req: RunToCompletionRequest,
    session: AsyncSession = Depends(get_session),
):
    """Run until answer or max_steps."""
    svc = get_run_service()
    try:
        info = await svc.run_to_completion(session, run_id, req.max_steps)
    except ValueError as e:
        raise HTTPException(404, str(e))
    return RunResponse(
        run_id=info.run_id,
        status=info.status,
        codelet_count=info.codelet_count,
        temperature=info.temperature,
        initial=info.initial,
        modified=info.modified,
        target=info.target,
        answer=info.answer,
        justify_mode=info.justify_mode,
        spreading_threshold=info.spreading_threshold,
        mode=info.mode,
    )


@router.post("/{run_id}/stop")
async def stop_run(run_id: int):
    """Interrupt a running run."""
    svc = get_run_service()
    try:
        svc.stop_run(run_id)
    except ValueError as e:
        raise HTTPException(404, str(e))
    return {"run_id": run_id, "stopped": True}


@router.post("/{run_id}/reset", response_model=RunResponse)
async def reset_run(
    run_id: int,
    session: AsyncSession = Depends(get_session),
):
    """Reset run to initial state."""
    svc = get_run_service()
    try:
        info = await svc.reset_run(session, run_id)
    except ValueError as e:
        raise HTTPException(404, str(e))
    return RunResponse(
        run_id=info.run_id,
        status=info.status,
        codelet_count=info.codelet_count,
        temperature=info.temperature,
        initial=info.initial,
        modified=info.modified,
        target=info.target,
        answer=info.answer,
        justify_mode=info.justify_mode,
        spreading_threshold=info.spreading_threshold,
        mode=info.mode,
    )


@router.delete("/{run_id}")
async def delete_run(
    run_id: int,
    session: AsyncSession = Depends(get_session),
):
    """Delete run and all state."""
    svc = get_run_service()
    await svc.delete_run(session, run_id)
    return {"run_id": run_id, "deleted": True}


@router.delete("")
async def delete_all_runs(
    session: AsyncSession = Depends(get_session),
):
    """Delete ALL runs, snapshots, trace events, and episodic memory."""
    svc = get_run_service()
    count = await svc.delete_all_runs(session)
    return {"deleted_count": count}


@router.get("/{run_id}/themespace")
async def get_themespace(run_id: int):
    """Current themespace state."""
    svc = get_run_service()
    state = svc.get_themespace_state(run_id)
    if state is None:
        raise HTTPException(404, f"Run {run_id} not found")
    return state


@router.get("/{run_id}/trace")
async def get_trace(
    run_id: int,
    event_type: str | None = None,
    limit: int = 100,
    offset: int = 0,
    session: AsyncSession = Depends(get_session),
):
    """Trace events from DB (with optional filtering).

    Falls back to in-memory for active runs if DB has no events yet.
    """
    svc = get_run_service()
    # Try DB first
    events = await svc.get_trace_events_from_db(
        session, run_id, event_type=event_type, limit=limit, offset=offset,
    )
    if not events:
        # Fall back to in-memory for active runs
        mem_events = svc.get_trace_events(
            run_id, event_type=event_type, limit=limit, offset=offset,
        )
        if mem_events is not None:
            events = mem_events
    return {"run_id": run_id, "events": events, "limit": limit, "offset": offset}


@router.get("/{run_id}/trace/export")
async def export_trace(run_id: int, session: AsyncSession = Depends(get_session)):
    """Export full trace as downloadable JSON."""
    from fastapi.responses import JSONResponse

    svc = get_run_service()
    events = await svc.get_trace_events_from_db(session, run_id, limit=100000)
    if not events:
        # Fall back to in-memory
        mem_events = svc.get_trace_events(run_id, limit=100000)
        if mem_events is not None:
            events = mem_events
    return JSONResponse(
        content={"run_id": run_id, "events": events or []},
        headers={"Content-Disposition": f"attachment; filename=trace_run_{run_id}.json"},
    )


# ``export`` is registered above ``/{event_number}``: FastAPI matches routes in
# registration order, so the literal path has to be declared before the parameterised
# one that would otherwise swallow it.
@router.get("/{run_id}/trace/{event_number}")
async def get_trace_event(run_id: int, event_number: int):
    """One Trace event in full — its structures, theme-pattern and strength.

    §2.4.3: Trace events are "themselves subject to examination by codelets"; MetaCat's
    Trace window makes them examinable by the user too, and a log with no addressable
    events is the one thing the Trace display exists not to be.
    """
    svc = get_run_service()
    detail = svc.describe_trace_event(run_id, event_number)
    if detail is None:
        raise HTTPException(404, f"Event {event_number} not found in run {run_id}")
    return detail


@router.post("/{run_id}/trace/{event_number}/display")
async def display_trace_event(run_id: int, event_number: int):
    """Impose that event's theme-pattern over the live Themespace, or restore it.

    The ``display`` message every MetaCat event answers, which saves the live state and
    imposes the episode's own pattern; calling it again puts the live state back.
    """
    svc = get_run_service()
    try:
        return svc.impose_trace_event(run_id, event_number)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from None


@router.post("/{run_id}/themespace/restore")
async def restore_themespace(run_id: int):
    """Stop displaying a past episode (Scheme: ``restore-current-state``)."""
    svc = get_run_service()
    try:
        return svc.restore_themespace(run_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from None


def _project_memory(memory) -> dict:
    """An in-process ``EpisodicMemory`` in the shape the Memory panel reads.

    A near-twin of ``RunService.get_memory_state``, which projects the *shared* memory
    and only that one; this projects whichever memory it is handed.  The duplication is
    small and the alternative — a parameter on the service method — would have to be
    added in ``server/services``, which this change does not touch.
    """
    return {
        "answers": [
            {
                "answer_id": a.answer_id,
                "run_id": a.run_id,
                "problem": list(a.problem),
                "top_rule_description": a.top_rule_description,
                "bottom_rule_description": a.bottom_rule_description,
                "top_rule_quality": a.top_rule_quality,
                "bottom_rule_quality": a.bottom_rule_quality,
                "quality": a.quality,
                "temperature": a.temperature,
                "themes": a.themes,
                "unjustified_slippages": a.unjustified_slippages,
                "activation": a.activation,
                "top_themes": a.top_themes,
                "vertical_themes": a.vertical_themes,
                "bottom_themes": a.bottom_themes,
                "unjustified_themes": a.unjustified_themes,
                "top_rule_abstractness": a.top_rule_abstractness,
                "bottom_rule_abstractness": a.bottom_rule_abstractness,
                "theme_abstractness": a.theme_abstractness,
                "is_coherent": a.is_coherent,
            }
            for a in memory.answers
        ],
        "snags": [
            {
                "snag_id": s.snag_id,
                "run_id": s.run_id,
                "problem": list(s.problem),
                "codelet_count": s.codelet_count,
                "temperature": s.temperature,
                "theme_pattern": s.theme_pattern,
                "description": s.description,
            }
            for s in memory.snags
        ],
    }


@router.get("/{run_id}/memory")
async def get_memory(run_id: int, session: AsyncSession = Depends(get_session)):
    """The Episodic Memory *this run* is actually thinking against.

    That is the shared Training Session memory in **every** mode.  Mode chooses where a
    run is recorded, not what it is: a Fast Run takes part in the session exactly as a
    Normal or Audit Run does, so it is reminded of earlier answers and its own answers
    are there for the runs that follow.

    A Fast Run is served from the live object rather than the database — it has no rows,
    which is the whole point — but the object is the same one.  ``scope`` says which
    read was taken, so a panel showing a Fast Run cannot be mistaken for one showing
    stale rows.
    """
    from server.services.sinks import MODE_FAST, MODE_NORMAL

    svc = get_run_service()
    runner = svc._runners.get(run_id)
    mode = svc._modes.get(run_id, MODE_NORMAL)
    if mode == MODE_FAST and runner is not None and runner.ctx is not None:
        return {
            **_project_memory(runner.ctx.memory),
            "scope": "live",
            "run_id": run_id,
            "mode": mode,
        }
    return {
        **await svc.get_memory_state_from_db(session),
        "scope": "shared",
        "run_id": run_id,
        "mode": mode,
    }


@router.get("/{run_id}/commentary")
async def get_commentary(
    run_id: int,
    eliza_mode: bool = False,
):
    """Commentary text for the given run."""
    svc = get_run_service()
    result = svc.get_commentary(run_id, eliza_mode=eliza_mode)
    if result is None:
        raise HTTPException(404, f"Run {run_id} not found")
    return result

