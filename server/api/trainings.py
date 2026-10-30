"""FastAPI router for Trainings: named, long-lived episodes of many problems over many seeds.

See ``server/services/training_service.py`` for the design.  A Training can be extended
while it runs (``POST /{id}/problems``), paused, resumed, closed and cancelled; problems
report their answer distribution as they finish, and ``GET /{id}/finished`` is a long-poll
cursor over the order in which they finished -- the surface an ML layer drives.  With
``memory = 'shared'`` the runs share one episode memory (a run copies it at its start and
merges its additions when it finishes); ``GET /{id}/memory`` serves it.

The routes work with or without the parallel plugin: without it the runs execute serially
in one child process, with identical results.
"""

from __future__ import annotations

import csv
import io
import json
from typing import Any, AsyncIterator, Literal

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from server.services.training_service import (
    MAX_PROBLEMS_PER_REQUEST,
    MAX_SEEDS_PER_PROBLEM,
    TrainingError,
    TrainingService,
    get_training_service,
)

LETTERS = r"^[A-Za-z]{1,64}$"


class ProblemInput(BaseModel):
    initial: str = Field(pattern=LETTERS)
    modified: str = Field(pattern=LETTERS)
    target: str = Field(pattern=LETTERS)
    #: Set for justification mode.
    answer: str | None = Field(default=None, pattern=LETTERS)
    seeds: int | None = Field(default=None, ge=1, le=MAX_SEEDS_PER_PROBLEM)
    tag: Any = None


class AddProblemsRequest(BaseModel):
    problems: list[ProblemInput] = Field(max_length=MAX_PROBLEMS_PER_REQUEST)


class CreateTrainingRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    note: str = Field(default="", max_length=10_000)
    #: Partial ``TrainingSettings``: memory, seeds_per_problem, seed_start, max_codelets,
    #: parameters, backend.  Each is validated by the service (422, or 400 for parameters
    #: and backend); omitted ones take the defaults.
    settings: dict[str, Any] | None = None
    #: Partial ``ErrorPolicy``; a bad value is a 400.
    policy: dict[str, Any] | None = None
    problems: list[ProblemInput] = Field(default_factory=list, max_length=MAX_PROBLEMS_PER_REQUEST)


class UpdateTrainingRequest(BaseModel):
    model_config = {"extra": "forbid"}  # settings cannot change after creation
    name: str | None = Field(default=None, min_length=1, max_length=200)
    note: str | None = Field(default=None, max_length=10_000)
    policy: dict[str, Any] | None = None


router = APIRouter(prefix="/api/trainings", tags=["trainings"])


def _service() -> TrainingService:
    service = get_training_service()
    if service is None:
        raise HTTPException(503, "The training service is not running (is the database available?).")
    return service


async def _call(coro):
    try:
        return await coro
    except TrainingError as exc:
        raise HTTPException(exc.status, exc.detail) from exc


def _dump(problems: list[ProblemInput]) -> list[dict[str, Any]]:
    return [p.model_dump() for p in problems]


@router.get("")
async def list_trainings() -> dict[str, Any]:
    """Every Training (newest first), the executor's state, the limits and the defaults."""
    service = _service()
    return {
        "trainings": await service.list_trainings(),
        "executor": service.executor_info(),
        "limits": service.limits(),
        "defaults": service.defaults(),
    }


@router.post("", status_code=201)
async def create_training(req: CreateTrainingRequest) -> dict[str, Any]:
    """Create a Training, optionally with its first problems."""
    return await _call(_service().create_training(
        name=req.name, note=req.note, settings=req.settings, policy=req.policy,
        problems=_dump(req.problems),
    ))


@router.get("/{training_id}")
async def get_training(training_id: int) -> dict[str, Any]:
    """One Training's summary, with live progress."""
    return await _call(_service().summary(training_id))


@router.patch("/{training_id}")
async def update_training(training_id: int, req: UpdateTrainingRequest) -> dict[str, Any]:
    """Rename a Training, edit its note, or change its error policy (settings are fixed)."""
    return await _call(_service().update(training_id, req.name, req.note, req.policy))


@router.get("/{training_id}/memory")
async def training_memory(training_id: int) -> dict[str, Any]:
    """The episode memory, newest first, in the shape ``GET /api/memory`` uses (shared only)."""
    from server.api.runs import get_run_service

    memory = await _call(_service().memory_of(training_id))
    state = get_run_service().get_memory_state(memory)
    return {"answers": list(reversed(state["answers"])), "snags": list(reversed(state["snags"]))}


@router.post("/{training_id}/problems", status_code=201)
async def add_problems(training_id: int, req: AddProblemsRequest) -> dict[str, Any]:
    """Insert problems into a training, whether or not it is running (409 once closed)."""
    return await _call(_service().add_problems(training_id, _dump(req.problems)))


@router.get("/{training_id}/problems")
async def list_problems(
    training_id: int,
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
    """A training's problems, filtered, sorted and paged."""
    return await _call(_service().list_problems(training_id, status, q, sort, order, offset, limit))


@router.get("/{training_id}/problems/{problem_id}")
async def get_problem(training_id: int, problem_id: int) -> dict[str, Any]:
    """One problem with its full answer distribution."""
    return await _call(_service().get_problem(training_id, problem_id))


@router.get("/{training_id}/problems/{problem_id}/runs")
async def problem_runs(training_id: int, problem_id: int) -> dict[str, Any]:
    """A problem's runs in seed order (those finished so far while it is running)."""
    return {"runs": await _call(_service().problem_runs(training_id, problem_id))}


@router.post("/{training_id}/problems/{problem_id}/cancel")
async def cancel_problem(training_id: int, problem_id: int) -> dict[str, Any]:
    """Drop a problem's remaining seeds; the runs already finished are kept."""
    return await _call(_service().cancel_problem(training_id, problem_id))


@router.get("/{training_id}/finished")
async def finished(
    training_id: int,
    after: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    wait: float = Query(0.0, ge=0.0, le=60.0),
) -> dict[str, Any]:
    """Problems finished after a cursor, in the order they finished; long-polls with wait."""
    return await _call(_service().finished(training_id, after, limit, wait))


@router.post("/{training_id}/pause")
async def pause(training_id: int) -> dict[str, Any]:
    """Start nothing new; runs in flight finish and are kept."""
    return await _call(_service().pause(training_id))


@router.post("/{training_id}/resume")
async def resume(training_id: int) -> dict[str, Any]:
    """Continue a paused training."""
    return await _call(_service().resume(training_id))


@router.post("/{training_id}/close")
async def close(training_id: int) -> dict[str, Any]:
    """Accept no more problems; the training is finished once the last one finishes."""
    return await _call(_service().close(training_id))


@router.post("/{training_id}/cancel")
async def cancel(training_id: int) -> dict[str, Any]:
    """Cancel every queued and running problem."""
    return await _call(_service().cancel_training(training_id))


@router.delete("/{training_id}", status_code=204)
async def delete_training(training_id: int) -> None:
    """Cancel, then delete the training with its problems and runs."""
    await _call(_service().delete_training(training_id))


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
    service: TrainingService, training_id: int, what: str, fmt: str
) -> AsyncIterator[str]:
    columns = {"problems": PROBLEM_COLUMNS, "distribution": DISTRIBUTION_COLUMNS,
               "runs": RUN_COLUMNS}[what]
    first = True
    if what == "runs":
        pages = service.iter_run_rows(training_id)
    else:
        pages = service.iter_problem_dicts(training_id)
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


@router.get("/{training_id}/export")
async def export(
    training_id: int,
    what: Literal["problems", "distribution", "runs"] = "problems",
    format: Literal["csv", "json"] = "csv",
) -> StreamingResponse:
    """Download a training: its problems, answer distributions, or every run (NDJSON for json)."""
    service = _service()
    await _call(service.summary(training_id))  # 404 before the stream starts
    if format == "csv":
        media, ext = "text/csv", "csv"
    elif what == "runs":
        media, ext = "application/x-ndjson", "ndjson"
    else:
        media, ext = "application/json", "json"
    return StreamingResponse(
        _export_stream(service, training_id, what, format),
        media_type=media,
        headers={"Content-Disposition": f'attachment; filename="training-{training_id}-{what}.{ext}"'},
    )
