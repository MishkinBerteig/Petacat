"""FastAPI router for Training Mode Sessions: named, long-lived episodes of many
problems over many seeds.

See ``server/services/training_mode_session_service.py`` for the design.  A Training Mode Session is created Stopped
and is started, paused, resumed and stopped any number of times (``POST /{id}/start``,
``/pause``, ``/resume``, ``/stop``); ``POST /{id}/cancel`` is an action that cancels every
queued and in-flight problem and changes no state.  Its states are stopped, starting,
running, paused and stopping; a live session writes nothing to the database until it is
Stopped, so every summary and change report of a live session says ``persisted: false`` and
carries ``saved_through`` and ``unsaved``, and a change to a session that is starting or
stopping is refused with 409 ``busy``.  Problems can be added in any other state
(``POST /{id}/problems``); they report their answer distribution as they finish, and
``GET /{id}/finished`` is a long-poll cursor over the order in which they finished -- the
surface an ML layer drives.  Every Training Mode Session has one Episodic Memory that its runs share (a
run copies it at its start and merges its additions when it finishes); ``GET /{id}/memory``
serves it.  No route clears it: deleting the whole Training Mode Session removes it.  Every
Training Mode Session also has its own evolving configuration, starting from its Starting
Conceptual State (``settings.configuration_base`` plus ``settings.parameters`` folded in at
creation); every summary carries its ``configuration`` block, and every run its
``configuration_revision``, ``episode_version`` and ``config_hash``.

The routes work with or without the parallel plugin: without it the runs execute serially
in one child process, with identical results.
"""

from __future__ import annotations

import csv
import io
import json
from typing import Any, AsyncIterator, Literal

from fastapi import APIRouter, HTTPException, Query
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field, model_validator

from server.services import session_configuration_views as views
from server.services.configuration_writer import ChangeError, error_response
from server.services.problem_text import check_problem
from server.services.training_mode_session_service import (
    MAX_PROBLEMS_PER_REQUEST,
    MAX_SEEDS_PER_PROBLEM,
    SessionError,
    TrainingModeSessionService,
    get_training_mode_session_service,
)

class ProblemInput(BaseModel):
    #: Any Unicode text, stored exactly; see ``server.services.problem_text``.
    initial: str
    modified: str
    target: str
    #: Set for justification mode.
    answer: str | None = None
    seeds: int | None = Field(default=None, ge=1, le=MAX_SEEDS_PER_PROBLEM)
    tag: Any = None

    @model_validator(mode="after")
    def _problem_text(self) -> "ProblemInput":
        # Refuses only the empty string (initial, modified, target; an answer is null or
        # non-empty), U+0000 and a lone surrogate; every other string is valid.
        check_problem(self.initial, self.modified, self.target, self.answer, require_nonempty=True)
        return self


class AddProblemsRequest(BaseModel):
    problems: list[ProblemInput] = Field(max_length=MAX_PROBLEMS_PER_REQUEST)


class CreateSessionRequest(BaseModel):
    model_config = {"extra": "forbid"}  # e.g. a ``memory`` field is refused (422)
    name: str = Field(min_length=1, max_length=200)
    note: str = Field(default="", max_length=10_000)
    #: Partial ``SessionSettings``: seeds_per_problem, seed_start, max_codelets,
    #: parameters, backend, configuration_base.  Each is validated by the service (422, or 400
    #: for parameters and backend); omitted ones take the defaults.
    settings: dict[str, Any] | None = None
    #: Partial ``ErrorPolicy``; a bad value is a 400.
    policy: dict[str, Any] | None = None
    problems: list[ProblemInput] = Field(default_factory=list, max_length=MAX_PROBLEMS_PER_REQUEST)


class StartRequest(BaseModel):
    model_config = {"extra": "forbid"}
    #: Start in the Paused state instead of Running.
    paused: bool = False


class UpdateSessionRequest(BaseModel):
    model_config = {"extra": "forbid"}  # settings cannot change after creation
    name: str | None = Field(default=None, min_length=1, max_length=200)
    note: str | None = Field(default=None, max_length=10_000)
    policy: dict[str, Any] | None = None


router = APIRouter(prefix="/api/training-mode/sessions", tags=["training_mode_sessions"])


def _service() -> TrainingModeSessionService:
    service = get_training_mode_session_service()
    if service is None:
        raise HTTPException(503, "The session service is not running (is the database available?).")
    return service


async def _call(coro):
    try:
        return await coro
    except SessionError as exc:
        raise HTTPException(exc.status, exc.detail) from exc


def _dump(problems: list[ProblemInput]) -> list[dict[str, Any]]:
    return [p.model_dump() for p in problems]


@router.get("")
async def list_sessions() -> dict[str, Any]:
    """Every Training Mode Session (newest first), the executor's state, the limits and the defaults."""
    service = _service()
    return {
        "sessions": await service.list_sessions(),
        "executor": service.executor_info(),
        "limits": service.limits(),
        "defaults": service.defaults(),
    }


@router.post("", status_code=201)
async def create_session(req: CreateSessionRequest) -> dict[str, Any]:
    """Create a Training Mode Session, optionally with its first problems."""
    return await _call(_service().create_session(
        name=req.name, note=req.note, settings=req.settings, policy=req.policy,
        problems=_dump(req.problems),
    ))


@router.get("/{session_id}")
async def get_session(session_id: int) -> dict[str, Any]:
    """One Training Mode Session's summary, with live progress."""
    return await _call(_service().summary(session_id))


@router.patch("/{session_id}")
async def update_session(session_id: int, req: UpdateSessionRequest) -> dict[str, Any]:
    """Rename a Training Mode Session, edit its note, or change its error policy (settings are fixed)."""
    return await _call(_service().update(session_id, req.name, req.note, req.policy))


@router.get("/{session_id}/memory")
async def training_mode_session_memory(session_id: int) -> dict[str, Any]:
    """The Training Mode Session's Episodic Memory, newest first, in the shape ``GET /api/memory`` uses."""
    from server.api.runs import get_run_service

    memory = await _call(_service().memory_of(session_id))
    state = get_run_service().get_memory_state(memory)
    return {"answers": list(reversed(state["answers"])), "snags": list(reversed(state["snags"]))}


@router.post("/{session_id}/problems", status_code=201)
async def add_problems(session_id: int, req: AddProblemsRequest) -> dict[str, Any]:
    """Insert problems: a Stopped session stores them at once, a live one queues them in memory
    (``persisted: false``, written at Stop); 409 ``busy`` while starting or stopping."""
    return await _call(_service().add_problems(session_id, _dump(req.problems)))


@router.get("/{session_id}/problems")
async def list_problems(
    session_id: int,
    status: Literal["queued", "running", "finished", "cancelled"] | None = None,
    q: str | None = None,
    sort: Literal[
        "id", "runs_done", "top_fraction", "none_fraction", "distinct", "errors",
        "mean_codelets", "finished_seq",
    ] = "id",
    order: Literal["asc", "desc"] = "asc",
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
) -> dict[str, Any]:
    """A session's problems, filtered, sorted and paged."""
    return await _call(_service().list_problems(session_id, status, q, sort, order, offset, limit))


@router.get("/{session_id}/problems/{problem_id}")
async def get_problem(session_id: int, problem_id: int) -> dict[str, Any]:
    """One problem with its full answer distribution."""
    return await _call(_service().get_problem(session_id, problem_id))


@router.get("/{session_id}/problems/{problem_id}/runs")
async def problem_runs(session_id: int, problem_id: int) -> dict[str, Any]:
    """A problem's runs in seed order (those finished so far while it is running)."""
    return {"runs": await _call(_service().problem_runs(session_id, problem_id))}


@router.post("/{session_id}/problems/{problem_id}/cancel")
async def cancel_problem(session_id: int, problem_id: int) -> dict[str, Any]:
    """Drop a problem's remaining seeds; the runs already finished are kept."""
    return await _call(_service().cancel_problem(session_id, problem_id))


@router.get("/{session_id}/finished")
async def finished(
    session_id: int,
    after: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    wait: float = Query(0.0, ge=0.0, le=60.0),
) -> dict[str, Any]:
    """Problems finished after a cursor, in the order they finished; long-polls with wait."""
    return await _call(_service().finished(session_id, after, limit, wait))


@router.post("/{session_id}/start")
async def start(session_id: int, req: StartRequest | None = None) -> dict[str, Any]:
    """Stopped to Running (or Paused when ``paused`` is true); a live session is unchanged.
    It reads the database and writes nothing; 409 ``busy`` while the session is stopping."""
    return await _call(_service().start_session(session_id, paused=bool(req and req.paused)))


@router.post("/{session_id}/pause")
async def pause(session_id: int) -> dict[str, Any]:
    """Start nothing new; runs in flight finish and are kept (409 when Stopped)."""
    return await _call(_service().pause(session_id))


@router.post("/{session_id}/resume")
async def resume(session_id: int) -> dict[str, Any]:
    """Continue a paused session (409 when Stopped)."""
    return await _call(_service().resume(session_id))


@router.post("/{session_id}/stop")
async def stop(session_id: int) -> dict[str, Any]:
    """Running or Paused to Stopped: runs in flight are drained (up to the drain timeout), then
    everything the session produced is written in one transaction, and it can be started again.
    A failed write leaves it Paused with its work intact (500). A Stopped session is unchanged."""
    return await _call(_service().stop_session(session_id))


@router.post("/{session_id}/cancel")
async def cancel(session_id: int) -> dict[str, Any]:
    """Cancel every queued and in-flight problem. An action, not a state: the state is unchanged."""
    return await _call(_service().cancel_session(session_id))


# ---------------------------------------------------------------------------
# The session's configuration: changes from every learning source, and its history
# ---------------------------------------------------------------------------


@router.post("/{session_id}/changes")
async def post_changes(session_id: int, body: dict[str, Any]):
    """The external route: submit a batch of changes to the session's configuration.

    The change API scoped to this one session (``POST /api/configurations/{id}/changes`` is the
    same function): the body is ``{source, actor, note, base_version, base_mode, on_op_failure,
    dry_run, ops}`` and ``source`` defaults to ``external``.  ``base_version`` is REQUIRED on this
    route: an integer revision, or ``"head"`` for the session's current version; without it the
    answer is 400 (``base_version must be an integer revision or "head"``).  Every learning source
    (the in-worker learner, this route and the Admin view) may change anything, and no rule refuses
    a change.  By state: Running or Paused, the batch is accepted into memory and the report
    says ``persisted: false`` (written at Stop); Stopped, it is written at once
    (``persisted: true``); Starting or Stopping, 409 ``busy``.  A refusal is ``{ok: false,
    error, status, message, problems}``: 400 or 422 for a malformed batch, 409 for ``stale``
    (``base_mode: strict`` only) or ``key_exists``, 404 for an unknown session.
    """
    batch = dict(body)
    batch.setdefault("source", "external")
    try:
        return await _service().submit_changes(session_id, batch)
    except ChangeError as exc:
        return error_response(exc)
    except SessionError as exc:
        raise HTTPException(exc.status, exc.detail) from exc


@router.get("/{session_id}/journal")
async def session_journal(
    session_id: int,
    from_: int | None = Query(None, alias="from", ge=0),
    to: int | None = Query(None, ge=0),
    source: str | None = None,
    actor: str | None = None,
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    detail: bool = False,
) -> dict[str, Any]:
    """The session's journal timeline, newest first: version, source, actor, the causing run,
    the counts of ops by kind, the hash. ``from`` and ``to`` are versions (inclusive); a live
    session's entries not yet stored are included with ``pending: true``."""
    return await _call(views.journal(
        _service(), session_id, from_version=from_, to_version=to, source=source, actor=actor,
        limit=limit, offset=offset, detail=detail))


@router.get("/{session_id}/configuration")
async def session_configuration(
    session_id: int, version: int | None = Query(None, ge=0), table: str | None = None
) -> dict[str, Any]:
    """The configuration at a version (the current one by default): the table row counts, or
    with ``table`` that table's rows. Labelled ``live`` or ``stored`` with ``saved_through``
    and ``unsaved``."""
    return await _call(views.configuration(_service(), session_id, version, table))


@router.get("/{session_id}/configuration/diff")
async def session_configuration_diff(
    session_id: int, from_: int = Query(alias="from", ge=0), to: int | None = Query(None, ge=0)
) -> dict[str, Any]:
    """The rows added, removed or changed going from version ``from`` to version ``to`` (the
    current version by default)."""
    return await _call(views.diff(_service(), session_id, from_, to))


@router.get("/{session_id}/slipnet")
async def session_slipnet(session_id: int, version: int | None = Query(None, ge=0)) -> dict[str, Any]:
    """The Slipnet graph at a version: nodes, links and layout, with the nodes that have no
    layout row."""
    return await _call(views.slipnet(_service(), session_id, version))


@router.delete("/{session_id}", status_code=204)
async def delete_session(session_id: int) -> None:
    """Delete the session with its Episodic Memory, problems and runs. A live one is settled
    first, with no Stop write; nothing is left behind."""
    await _call(_service().delete_session(session_id))


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

PROBLEM_COLUMNS = [
    "id", "initial", "modified", "target", "answer", "seeds", "seed_start", "status",
    "runs_done", "errors", "capped", "mean_codelets", "top_answer", "top_fraction", "none_fraction",
    "distinct", "finished_seq", "added_at", "started_at", "finished_at", "tag",
]
DISTRIBUTION_COLUMNS = [
    "problem_id", "initial", "modified", "target", "answer_key", "count", "fraction",
    "mean_quality",
]
RUN_COLUMNS = [
    "problem_id", "initial", "modified", "target", "problem_answer", "seed", "status",
    "key", "answer", "answers", "codelets", "seconds", "temperature", "answer_quality", "error",
    "config_hash", "attempts", "seq", "memory_version", "memory_added",
]


def _csv_chunk(columns: list[str], rows: list[dict], header: bool) -> str:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=columns, extrasaction="ignore", lineterminator="\n")
    if header:
        writer.writeheader()
    for row in rows:
        writer.writerow({
            k: (json.dumps(v) if isinstance(v, (list, dict)) else ("" if v is None else v))
            for k, v in row.items()
        })
    return buf.getvalue()


def _flat_problem(p: dict) -> dict:
    top = p["top"][0] if p["top"] else None
    return {**p, "top_answer": top["answer"] if top else None,
            "top_fraction": top["fraction"] if top else None}


def _flat_distribution(p: dict) -> list[dict]:
    return [
        {"problem_id": p["id"], "initial": p["initial"], "modified": p["modified"],
         "target": p["target"], "answer_key": d["answer"], "count": d["count"],
         "fraction": d["fraction"], "mean_quality": d["mean_quality"]}
        for d in p.get("distribution", [])
    ]


async def _export_stream(
    service: TrainingModeSessionService, session_id: int, what: str, fmt: str
) -> AsyncIterator[str]:
    columns = {"problems": PROBLEM_COLUMNS, "distribution": DISTRIBUTION_COLUMNS,
               "runs": RUN_COLUMNS}[what]
    first = True
    if what == "runs":
        pages = service.iter_run_rows(session_id)
    else:
        pages = service.iter_problem_dicts(session_id)
    if fmt == "json" and what != "runs":
        yield "["
    wrote_csv_header = False
    async for page in pages:
        if what == "problems":
            rows = [_flat_problem(p) for p in page]
        elif what == "distribution":
            rows = [r for p in page for r in _flat_distribution(p)]
        else:
            rows = page
        if fmt == "csv":
            yield _csv_chunk(columns, rows, header=not wrote_csv_header)
            wrote_csv_header = True
        elif what == "runs":
            yield "".join(json.dumps(r) + "\n" for r in rows)
        else:
            for r in rows:
                yield ("" if first else ",") + json.dumps(r)
                first = False
    if fmt == "csv" and not wrote_csv_header:
        yield _csv_chunk(columns, [], header=True)
    if fmt == "json" and what != "runs":
        yield "]"


@router.get("/{session_id}/export")
async def export(
    session_id: int,
    what: Literal["problems", "distribution", "runs", "configuration", "journal"] = "problems",
    format: Literal["csv", "json"] | None = None,
    version: int | None = Query(None, ge=0),
) -> StreamingResponse:
    """Download a session: its problems, answer distributions, or every run (CSV by default;
    NDJSON for runs as json), or ``what=configuration`` (the configuration at ``version``, the
    current one by default, as one bundle) or ``what=journal`` (every entry in full), both JSON
    only. For a live session the stored rows are followed by a tail from memory, and the
    header ``X-Export-Source: stored+live-tail`` says so."""
    service = _service()
    summary = await _call(service.summary(session_id))  # 404 before the stream starts
    if what in ("configuration", "journal"):
        if format == "csv":
            raise HTTPException(400, f"what={what} is JSON only")
        if what == "configuration":
            body = await _call(views.export_configuration(service, session_id, version))
        else:
            body = await _call(views.export_journal(service, session_id))
        headers = {"Content-Disposition": f'attachment; filename="session-{session_id}-{what}.json"',
                   "X-Export-Source": "live" if summary["source"] == "live" else "stored"}
        return JSONResponse(jsonable_encoder(body), headers=headers)
    format = format or "csv"
    if format == "csv":
        media, ext = "text/csv", "csv"
    elif what == "runs":
        media, ext = "application/x-ndjson", "ndjson"
    else:
        media, ext = "application/json", "json"
    headers = {"Content-Disposition": f'attachment; filename="session-{session_id}-{what}.{ext}"'}
    if service.is_live(session_id):
        headers["X-Export-Source"] = "stored+live-tail"
    return StreamingResponse(_export_stream(service, session_id, what, format), media_type=media, headers=headers)
