"""FastAPI router for run lifecycle endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from server.db import get_session

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


class StepRequest(BaseModel):
    n: int = 1


class RunToCompletionRequest(BaseModel):
    max_steps: int = 0


class RunResponse(BaseModel):
    run_id: int
    status: str
    codelet_count: int
    temperature: float
    initial: str
    modified: str
    target: str
    answer: str | None


class RunListResponse(BaseModel):
    runs: list[RunResponse]
    total: int
    limit: int
    offset: int


class StepResponse(BaseModel):
    codelet_count: int
    codelet_type: str
    answer_found: bool = False
    answer: str | None = None


# ------------------------------------------------------------------
# Existing endpoints
# ------------------------------------------------------------------


@router.post("", response_model=RunResponse)
async def create_run(
    req: CreateRunRequest,
    session: AsyncSession = Depends(get_session),
):
    svc = get_run_service()
    info = await svc.create_run(
        session, req.initial, req.modified, req.target, req.answer, req.seed
    )
    return RunResponse(
        run_id=info.run_id,
        status=info.status,
        codelet_count=info.codelet_count,
        temperature=info.temperature,
        initial=info.initial,
        modified=info.modified,
        target=info.target,
        answer=info.answer,
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
    )


@router.post("/{run_id}/step", response_model=list[StepResponse])
async def step_run(
    run_id: int,
    req: StepRequest,
    session: AsyncSession = Depends(get_session),
):
    svc = get_run_service()
    try:
        results = await svc.step(session, run_id, req.n)
    except ValueError as e:
        raise HTTPException(404, str(e))
    return [
        StepResponse(
            codelet_count=r.codelet_count,
            codelet_type=r.codelet_type,
            answer_found=r.answer_found,
            answer=r.answer,
        )
        for r in results
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
    svc = get_run_service()
    temp = svc.get_temperature(run_id)
    if temp is None:
        raise HTTPException(404, f"Run {run_id} not found")
    return {"temperature": temp}


# ------------------------------------------------------------------
# New endpoints
# ------------------------------------------------------------------


@router.get("", response_model=RunListResponse)
async def list_runs(
    limit: int = 50,
    offset: int = 0,
    session: AsyncSession = Depends(get_session),
):
    """List all runs (paginated)."""
    svc = get_run_service()
    runs, total = await svc.list_runs(session, limit=limit, offset=offset)
    return RunListResponse(
        runs=[
            RunResponse(
                run_id=r.run_id,
                status=r.status,
                codelet_count=r.codelet_count,
                temperature=r.temperature,
                initial=r.initial,
                modified=r.modified,
                target=r.target,
                answer=r.answer,
            )
            for r in runs
        ],
        total=total,
        limit=limit,
        offset=offset,
    )


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


@router.get("/{run_id}/memory")
async def get_memory(run_id: int, session: AsyncSession = Depends(get_session)):
    """Episodic memory contents (cross-run, from DB)."""
    svc = get_run_service()
    return await svc.get_memory_state_from_db(session)


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
