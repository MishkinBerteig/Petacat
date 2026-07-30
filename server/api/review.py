"""FastAPI router for the review surfaces (WP3.9).

A separate module from ``api/runs.py`` rather than more endpoints in it, because the
two answer different questions and fail differently.  Every endpoint in ``runs.py`` is
about a *live* run: it either drives a runner or reads one out of
``RunService._runners``, and its 404 means "no engine with that id is loaded".  Nothing
here touches a live runner at all — these read rows that outlive the process that wrote
them, and their 404 means "nothing was recorded".  Serving both notions of "not found"
from one file would make it impossible to tell, from the outside, which one a caller
had hit.

The routes are grouped by what is being reviewed rather than by mode, because a
Training Session mixes modes freely and the browser has to list them together.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from server.db import get_session
from server.models.run import AuditAction, Run, RunStateCapture, TrainingSession
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


class SessionSummary(BaseModel):
    session_id: int
    started_at: datetime | None
    ended_at: datetime | None
    note: str = ""
    run_count: int
    first_run_at: datetime | None
    last_run_at: datetime | None
    #: A session ends when Episodic Memory is cleared; until then it can gain Runs.
    is_open: bool


class SessionListResponse(BaseModel):
    sessions: list[SessionSummary]
    total: int
    limit: int
    offset: int


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
    #: Which Training Session contains this Run.  Absent when the Run was reached
    #: *through* its session, because the caller already knows; present when it was
    #: looked up by id, because then the session is the thing they do not know.
    session_id: int | None = None


class SessionDetailResponse(BaseModel):
    session_id: int
    started_at: datetime | None
    ended_at: datetime | None
    note: str = ""
    is_open: bool
    runs: list[RunSummary]


class CaptureSummary(BaseModel):
    capture_id: int
    boundary: str
    codelet_count: int
    created_at: datetime | None


class CaptureListResponse(BaseModel):
    run_id: int
    captures: list[CaptureSummary]


class SessionNoteRequest(BaseModel):
    """What the reader wants this Training Session to be remembered as.

    A Training Session is not created deliberately — it is the span between two memory
    clears — so the only thing that can distinguish one from another after the fact is
    a number and a date range.  The note is the one field that lets a reader say what
    the session was *for*, which is what makes a list of them worth keeping.
    """

    note: str = ""


class SessionNoteResponse(BaseModel):
    session_id: int
    note: str


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
# Training Sessions
# ------------------------------------------------------------------


@router.get("/sessions", response_model=SessionListResponse)
async def list_sessions(
    limit: int = 50,
    offset: int = 0,
    session: AsyncSession = Depends(get_session),
):
    """Training Sessions, newest first, with Run counts and date range."""
    svc = get_review_service()
    sessions, total = await svc.list_sessions(session, limit=limit, offset=offset)
    return SessionListResponse(
        sessions=[SessionSummary(**s) for s in sessions],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/sessions/{session_id}", response_model=SessionDetailResponse)
async def get_session_runs(
    session_id: int,
    session: AsyncSession = Depends(get_session),
):
    """The sequence of Runs in one Training Session."""
    svc = get_review_service()
    try:
        detail = await svc.get_session_runs(session, session_id)
    except ReviewError as exc:
        raise _fail(exc) from None
    return SessionDetailResponse(
        **{**detail, "runs": [RunSummary(**r) for r in detail["runs"]]}
    )


@router.put("/sessions/{session_id}/note", response_model=SessionNoteResponse)
async def set_session_note(
    session_id: int,
    req: SessionNoteRequest,
    session: AsyncSession = Depends(get_session),
):
    """Set a Training Session's note.

    Written here rather than through ``ReviewService`` because the service reads the
    record and this is the one thing about a session a person may change; keeping the
    write beside the read would make the service's contract — "nothing here mutates" —
    no longer true of it.

    A missing session is a 404 rather than a silent no-op: a note the caller believes
    was saved and was not is worse than an error, because it is discovered much later.
    """
    result = await session.execute(
        update(TrainingSession)
        .where(TrainingSession.id == session_id)
        .values(note=req.note)
    )
    if (result.rowcount or 0) == 0:
        raise HTTPException(404, f"no Training Session {session_id}")
    await session.commit()
    return SessionNoteResponse(session_id=session_id, note=req.note)


# ------------------------------------------------------------------
# One recorded Run, by id
# ------------------------------------------------------------------


@router.get("/runs/{run_id}", response_model=RunSummary)
async def get_recorded_run(
    run_id: int,
    session: AsyncSession = Depends(get_session),
):
    """One Run's recorded summary, without knowing which session it belongs to.

    The session browser reaches a Run by opening the session that contains it, which is
    the right way round when the reader is browsing.  It is the wrong way round when
    they already have a Run in mind — coming from Run History on the dashboard, say —
    because they would have to find the session first, and the session is exactly the
    thing they do not know.  This is the same projection ``get_session_runs`` produces
    for one Run.
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
        session_id=row.session_id,
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
