"""FastAPI router for the review surfaces (WP3.9).

A separate module from ``api/runs.py`` rather than more endpoints in it, because the
two answer different questions and fail differently.  Every endpoint in ``runs.py`` is
about a *live* run: it either drives a runner or reads one out of
``RunService._runners``, and its 404 means "no engine with that id is loaded".  Nothing
here touches a live runner at all — these read rows that outlive the process that wrote
them, and their 404 means "nothing was recorded".  Serving both notions of "not found"
from one file would make it impossible to tell, from the outside, which one a caller
had hit.

The routes are grouped by what is being reviewed rather than by mode, because the
episodic-run timeline mixes modes freely and has to list them together.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from server.db import get_session
from server.models.run import AuditAction, Run, RunStateCapture
from server.services.capture_projection import CaptureFormatError
from server.services.review_service import (
    BackwardsNotSupported,
    NotRecorded,
    ReviewError,
)

router = APIRouter(prefix="/api/review", tags=["review"])

#: Set at app startup, as ``api/runs.py`` sets its ``RunService``.
_review_service = None


def get_review_service():
    if _review_service is None:
        raise HTTPException(500, "ReviewService not initialized")
    return _review_service


# ------------------------------------------------------------------
# Response models
# ------------------------------------------------------------------


class MemoryClear(BaseModel):
    """One event: Episodic Memory was cleared.

    ``after_run_id`` is the last recorded run before the clear (null if none), which
    places the marker exactly in the run sequence.
    """

    clear_id: int
    cleared_at: datetime
    after_run_id: int | None
    note: str = ""


class RunSummary(BaseModel):
    run_id: int
    mode: str
    status: str
    initial: str
    modified: str
    target: str
    answer: str | None
    justify_mode: bool = False
    seed: int
    codelet_count: int
    temperature: float
    spreading_threshold: int = 100
    #: Which configuration and which Episodic Memory the Run executed against (WP3.5).
    #: Part of the Run's identity: two Runs with one seed and different hashes are not
    #: the same experiment.
    config_hash: str | None = None
    memory_hash: str | None = None
    created_at: datetime | None
    #: How much record the Run actually left.  Zero and zero is a Fast Run, which is a
    #: statement about the mode rather than a fault.
    capture_count: int = 0
    action_count: int = 0


class RunTimelineItem(BaseModel):
    kind: Literal["run"] = "run"
    run: RunSummary


class ClearTimelineItem(BaseModel):
    kind: Literal["memory_cleared"] = "memory_cleared"
    clear: MemoryClear


class EpisodicRunsResponse(BaseModel):
    items: list[RunTimelineItem | ClearTimelineItem]
    total_runs: int
    total_clears: int
    limit: int
    offset: int


class CaptureSummary(BaseModel):
    capture_id: int
    boundary: str
    codelet_count: int
    created_at: datetime | None


class CaptureListResponse(BaseModel):
    run_id: int
    captures: list[CaptureSummary]


class AdvanceRequest(BaseModel):
    """Where to step the inspector to.

    A destination rather than a number of steps, so that a client which retries a
    request cannot double-step: asking twice for tick 40 lands on tick 40 both times.
    """

    to_codelet: int


# ------------------------------------------------------------------
# Error translation
#
# The service raises three kinds of thing and each deserves a different status.
# "Nothing was recorded" is a 404 because there is genuinely nothing at that address;
# an unrenderable capture is a 422 because the request was well-formed and the stored
# document is what cannot be served; and stepping backwards is a 409 because it is a
# conflict with the inspector's state rather than a malformed request.
# ------------------------------------------------------------------


def _fail(exc: Exception) -> HTTPException:
    if isinstance(exc, NotRecorded):
        return HTTPException(404, str(exc))
    if isinstance(exc, BackwardsNotSupported):
        return HTTPException(409, str(exc))
    if isinstance(exc, CaptureFormatError):
        return HTTPException(422, str(exc))
    return HTTPException(400, str(exc))


# ------------------------------------------------------------------
# The episodic-run timeline
# ------------------------------------------------------------------


@router.get("/episodic-runs", response_model=EpisodicRunsResponse)
async def list_episodic_runs(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_session),
):
    """Metacat Mode's recorded episodic runs, newest first, with Episodic Memory clears.

    ``limit`` and ``offset`` count runs.  A clear is interleaved in its exact place in
    the run sequence (``after_run_id``), so a reader sees which runs inherited which
    memory.  Notes on clears are edited through ``PUT /api/memory/clears/{id}/note``.
    """
    svc = get_review_service()
    return EpisodicRunsResponse(**await svc.episodic_timeline(session, limit, offset))


# ------------------------------------------------------------------
# One recorded Run, by id
# ------------------------------------------------------------------


@router.get("/runs/{run_id}", response_model=RunSummary)
async def get_recorded_run(
    run_id: int,
    session: AsyncSession = Depends(get_session),
):
    """One Run's recorded summary, by id.

    The timeline reaches a Run by paging, which is the right way round when the reader
    is browsing.  It is the wrong way round when they already have a Run in mind —
    coming from Run History on the dashboard, say.  This is the same projection the
    timeline produces for one Run.
    """
    row = (
        await session.execute(select(Run).where(Run.id == run_id))
    ).scalars().first()
    if row is None:
        # A Fast Run reaches here too: it has no row, which is the mode keeping its
        # promise.  The message says so rather than leaving the caller to guess.
        raise HTTPException(
            404,
            f"no recorded Run {run_id}. A Fast Run writes no row, so it cannot be "
            f"reviewed; re-run the problem in Normal or Audit mode.",
        )

    captures = (
        await session.execute(
            select(func.count())
            .select_from(RunStateCapture)
            .where(RunStateCapture.run_id == run_id)
        )
    ).scalar() or 0
    actions = (
        await session.execute(
            select(func.count())
            .select_from(AuditAction)
            .where(AuditAction.run_id == run_id)
        )
    ).scalar() or 0

    return RunSummary(
        run_id=row.id,
        mode=row.mode or "normal",
        status=row.status or "",
        initial=row.initial_string,
        modified=row.modified_string,
        target=row.target_string,
        answer=row.answer_string,
        justify_mode=bool(row.justify_mode),
        seed=row.seed,
        codelet_count=row.codelet_count or 0,
        temperature=row.temperature or 0.0,
        spreading_threshold=(
            100 if row.spreading_threshold is None else int(row.spreading_threshold)
        ),
        config_hash=row.config_hash,
        memory_hash=row.memory_hash,
        created_at=row.created_at,
        capture_count=captures,
        action_count=actions,
    )


# ------------------------------------------------------------------
# Normal review — the two captures and what changed between them
# ------------------------------------------------------------------


@router.get("/runs/{run_id}/captures", response_model=CaptureListResponse)
async def list_captures(
    run_id: int,
    session: AsyncSession = Depends(get_session),
):
    """Which boundary captures a Run wrote — without the blobs themselves."""
    svc = get_review_service()
    captures = await svc.list_captures(session, run_id)
    return CaptureListResponse(
        run_id=run_id, captures=[CaptureSummary(**c) for c in captures]
    )


@router.get("/runs/{run_id}/captures/{boundary}")
async def get_capture(
    run_id: int,
    boundary: str,
    session: AsyncSession = Depends(get_session),
):
    """One recorded capture, rendered in the shapes the live views already read.

    Not a Pydantic model: the payload is the Workspace, Slipnet, Themespace, Coderack,
    Trace and Memory display shapes, which are defined by ``serialization.py`` and
    already served unmodelled by ``GET /api/runs/{id}/workspace`` and its siblings.
    Restating them here would create a second definition that could drift from the one
    the dashboard is served against, and drift is the thing this package exists to
    prevent.
    """
    svc = get_review_service()
    try:
        return await svc.get_capture(session, run_id, boundary)
    except (ReviewError, CaptureFormatError) as exc:
        raise _fail(exc) from None


@router.get("/runs/{run_id}/captures/{boundary}/raw")
async def get_raw_capture(
    run_id: int,
    boundary: str,
    session: AsyncSession = Depends(get_session),
):
    """The capture exactly as written, for inspecting the format itself."""
    svc = get_review_service()
    try:
        return await svc.get_raw_capture(session, run_id, boundary)
    except ReviewError as exc:
        raise _fail(exc) from None


@router.get("/runs/{run_id}/comparison")
async def compare_run(
    run_id: int,
    session: AsyncSession = Depends(get_session),
):
    """What changed between a Normal Run's start and end captures."""
    svc = get_review_service()
    try:
        return await svc.compare_run(session, run_id)
    except (ReviewError, CaptureFormatError) as exc:
        raise _fail(exc) from None


# ------------------------------------------------------------------
# Audit review — the action log and the forward inspector
# ------------------------------------------------------------------


@router.get("/runs/{run_id}/actions")
async def list_actions(
    run_id: int,
    limit: int = 200,
    offset: int = 0,
    action_type: str | None = None,
    from_codelet: int | None = None,
    session: AsyncSession = Depends(get_session),
):
    """A page of the forward action log.

    Paginated by necessity: a 2,000-codelet Audit Run records thousands of actions.
    ``sequence`` is dense from 1 within a Run, so ``offset`` is also a position in the
    replay order.
    """
    svc = get_review_service()
    return await svc.list_actions(
        session,
        run_id,
        limit=limit,
        offset=offset,
        action_type=action_type,
        from_codelet=from_codelet,
    )


@router.get("/runs/{run_id}/actions/summary")
async def action_summary(
    run_id: int,
    session: AsyncSession = Depends(get_session),
):
    """Action counts by type and the tick range the log covers."""
    svc = get_review_service()
    return await svc.action_summary(session, run_id)


@router.post("/runs/{run_id}/inspector")
async def open_inspector(
    run_id: int,
    session: AsyncSession = Depends(get_session),
):
    """Restore the Run-start capture and sit at tick 0.

    Called again on an open inspection, this restarts it.  That is the only backwards
    movement offered, and it is re-opening rather than scrubbing: it needs none of the
    action-inversion machinery WP3.8 deliberately deferred.
    """
    svc = get_review_service()
    try:
        return await svc.open_inspector(session, run_id)
    except ReviewError as exc:
        raise _fail(exc) from None


@router.get("/runs/{run_id}/inspector")
async def inspector_state(
    run_id: int,
    session: AsyncSession = Depends(get_session),
):
    """Where the inspection is, and everything visible from there."""
    svc = get_review_service()
    try:
        return await svc.inspector_state(session, run_id)
    except ReviewError as exc:
        raise _fail(exc) from None


@router.post("/runs/{run_id}/inspector/advance")
async def advance_inspector(
    run_id: int,
    req: AdvanceRequest,
    session: AsyncSession = Depends(get_session),
):
    """Step the inspection forward to a tick.

    Refuses to go backwards with a 409 rather than silently restarting: a scrubber
    that quietly re-ran two thousand codelets when dragged left would be indis-
    tinguishable, from the outside, from one that had actually stepped back.
    """
    svc = get_review_service()
    try:
        return await svc.advance_inspector(session, run_id, req.to_codelet)
    except ReviewError as exc:
        raise _fail(exc) from None


@router.delete("/runs/{run_id}/inspector")
async def close_inspector(run_id: int):
    """Release a held inspection and the engine it carries."""
    svc = get_review_service()
    return {"run_id": run_id, "closed": svc.close_inspector(run_id)}
