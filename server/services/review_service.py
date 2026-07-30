"""Reading back what the persistence modes wrote (WP3.9).

Normal and Audit exist to be looked at, and until this module there was nothing that
looked at them.  Phase 0's whole reason for retiring the old snapshot system was that
it wrote 230 MB across ten runs that no code path could read, so shipping the writers
without the readers would repeat the mistake exactly.

Three surfaces, three mechanisms
--------------------------------
- **The Training Session browser** is ordinary aggregate SQL over ``runs``,
  ``training_sessions``, ``run_state_captures`` and ``audit_actions``.  It is meant to
  be scanned, so it answers in one query per level and never touches the engine.

- **Rendering a capture** goes through ``capture_projection``, which reads the record
  rather than restoring it.  See that module for why; the short version is that a
  reader which rebuilds objects proves the *objects* can be displayed, not that the
  *record* contains the display.

- **The Audit inspector** does restore, because it has to.  The audit log records the
  codelet that ran and the temperature at every tick, but not Slipnet or Themespace
  activation, and "the activation and temperature state at that instant" is what the
  plan asks for.  Reconstruction forward from the Run-start capture is the mechanism
  WP3.8 names for exactly this, and an Audit Run is serial and seeded, so re-executing
  it reproduces it.  ``_Inspector`` therefore holds a restored runner and walks it
  forward, and the inspector's own tests check its reconstruction against the recorded
  action log rather than trusting it.

Forward only
------------
The inspector cannot go backwards, and refuses rather than pretending: stepping back
would mean inverting actions from their ``before`` state, which WP3.8 deliberately
recorded the format for and deliberately did not build.  Restarting an inspection from
the beginning is offered instead, which is a different thing from scrubbing and does
not need the inverse machinery.
"""

from __future__ import annotations

import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Iterator

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from server.engine.runner import EngineRunner
from server.engine.state_graph import StateGraphError, restore_run_state
from server.engine.workspace_structures import WorkspaceStructure
from server.models.run import (
    AuditAction,
    Run,
    RunStateCapture,
    TrainingSession,
)
from server.services.capture_projection import project_capture

#: Boundaries a Run capture can be taken at.  Two, by definition of Normal mode.
BOUNDARIES = ("start", "end")


class ReviewError(Exception):
    """The record cannot answer the question asked of it."""


class NotRecorded(ReviewError):
    """There is nothing to review — most often a Fast Run, which writes nothing.

    Distinguished from "no such run" because they call for different words on screen:
    a Fast Run is not missing, it is a run that promised not to leave a record, and a
    review surface that reported it as an error would be reporting the design.
    """


class BackwardsNotSupported(ReviewError):
    """The Audit inspector was asked to step back.  Phase 0 is forward-only."""


#: "Leave the binding alone on the way in" — distinct from ``None``, which
#: ``init_mcat`` itself assigns and is therefore a real value.
_KEEP = object()


@contextmanager
def _themespace_binding(themespace: Any = _KEEP) -> Iterator[None]:
    """Restore the process-wide Themespace binding on exit; optionally set one first.

    ``WorkspaceStructure._themespace`` is a class attribute — the Scheme's global
    ``*themespace*``, mirrored — that structures consult for thematic compatibility
    (``bridges.py:295``, ``descriptions.py:149``).  ``init_mcat`` assigns it, so
    constructing an inspector's runner, or stepping one, would otherwise leave every
    *live* run computing bridge strengths against the inspected Run's themes.

    That hazard is not new — creating a second live run does the same thing — but an
    inspector is opened while other runs are in flight, which makes it easy to hit and
    impossible to attribute.  Borrowing and returning confines it to the review call:
    outside this block the binding is exactly what it was.

    Both uses appear here.  Opening an inspector lets ``init_mcat`` set the binding
    and only needs it put back, so it passes nothing; stepping one needs the
    inspector's own Themespace bound for the duration, so it passes that.

    It is sufficient because the engine work inside contains no ``await``.  A
    synchronous stretch cannot be interleaved with another request on the event loop,
    so no live run can observe the borrowed binding.  If review ever awaits mid-borrow,
    that stops being true and this becomes a lock rather than a swap.
    """
    previous = WorkspaceStructure.get_themespace()
    if themespace is not _KEEP:
        WorkspaceStructure.set_themespace(themespace)
    try:
        yield
    finally:
        WorkspaceStructure.set_themespace(previous)


# ─────────────────────────────────────────────────────────────────────────────
# The Audit inspector's held state
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class _Inspector:
    """A restored Run positioned at one tick, able to move forward only.

    Held between requests because the alternative is re-executing from the Run start on
    every tick, which turns stepping through a 2,000-codelet Run into quadratic work.
    Holding it makes each step cost one codelet.
    """

    run_id: int
    runner: EngineRunner
    #: Codelet count of the recorded Run's end, so the inspector knows where it stops.
    final_codelet_count: int
    last_used: float = field(default_factory=time.monotonic)

    @property
    def position(self) -> int:
        return self.runner.ctx.codelet_count if self.runner.ctx else 0


class ReviewService:
    """Reads the record; never mutates a Run.

    Given the ``MetadataProvider`` rather than the ``RunService`` on purpose: review
    must work for Runs whose runner is long gone, which is nearly all of them, so it
    has no business consulting the live-run registry.  What it needs the metadata for
    is the short names and conceptual depths a capture references by name, and the
    Slipnet a restored inspector runs against.
    """

    #: How many inspections may be held open at once.  Each holds a full engine, so
    #: this is a memory bound; the least recently used is dropped when it is exceeded.
    MAX_OPEN_INSPECTORS = 3

    def __init__(self, meta: Any) -> None:
        self.meta = meta
        self._inspectors: dict[int, _Inspector] = {}

    # ------------------------------------------------------------------
    # Training Sessions
    # ------------------------------------------------------------------

    async def list_sessions(
        self, session: AsyncSession, limit: int = 50, offset: int = 0
    ) -> tuple[list[dict], int]:
        """Sessions newest first, each with its Run count and date range.

        The counts are aggregated in the same query as the sessions rather than
        fetched per session, because the browser's job is to be fast to scan and a
        query per row is how a list of twenty sessions becomes twenty-one round trips.
        """
        total = (
            await session.execute(select(func.count()).select_from(TrainingSession))
        ).scalar() or 0

        rows = (
            await session.execute(
                select(
                    TrainingSession.id,
                    TrainingSession.started_at,
                    TrainingSession.ended_at,
                    TrainingSession.note,
                    func.count(Run.id).label("run_count"),
                    func.min(Run.created_at).label("first_run_at"),
                    func.max(Run.created_at).label("last_run_at"),
                )
                .select_from(TrainingSession)
                .outerjoin(Run, Run.session_id == TrainingSession.id)
                .group_by(TrainingSession.id)
                .order_by(TrainingSession.id.desc())
                .limit(limit)
                .offset(offset)
            )
        ).all()

        sessions = [
            {
                "session_id": r.id,
                "started_at": r.started_at,
                "ended_at": r.ended_at,
                "note": r.note or "",
                "run_count": r.run_count,
                "first_run_at": r.first_run_at,
                "last_run_at": r.last_run_at,
                "is_open": r.ended_at is None,
            }
            for r in rows
        ]
        return sessions, total

    async def get_session_runs(
        self, session: AsyncSession, session_id: int
    ) -> dict:
        """One session and the sequence of Runs in it.

        Each Run carries how much of a record it actually left — captures and audit
        actions — so the browser can say "nothing to review" for a Fast Run rather
        than opening an empty inspector and looking broken.
        """
        header = (
            await session.execute(
                select(TrainingSession).where(TrainingSession.id == session_id)
            )
        ).scalars().first()
        if header is None:
            raise NotRecorded(f"no Training Session {session_id}")

        capture_counts = dict(
            (
                await session.execute(
                    select(RunStateCapture.run_id, func.count())
                    .join(Run, Run.id == RunStateCapture.run_id)
                    .where(Run.session_id == session_id)
                    .group_by(RunStateCapture.run_id)
                )
            ).all()
        )
        action_counts = dict(
            (
                await session.execute(
                    select(AuditAction.run_id, func.count())
                    .join(Run, Run.id == AuditAction.run_id)
                    .where(Run.session_id == session_id)
                    .group_by(AuditAction.run_id)
                )
            ).all()
        )

        runs = (
            await session.execute(
                select(Run)
                .where(Run.session_id == session_id)
                .order_by(Run.id)
            )
        ).scalars().all()

        return {
            "session_id": header.id,
            "started_at": header.started_at,
            "ended_at": header.ended_at,
            "note": header.note or "",
            "is_open": header.ended_at is None,
            "runs": [
                {
                    "run_id": r.id,
                    "mode": r.mode or "normal",
                    "status": r.status or "",
                    "initial": r.initial_string,
                    "modified": r.modified_string,
                    "target": r.target_string,
                    "answer": r.answer_string,
                    "justify_mode": bool(r.justify_mode),
                    "seed": r.seed,
                    "codelet_count": r.codelet_count or 0,
                    "temperature": r.temperature or 0.0,
                    "spreading_threshold": (
                        100 if r.spreading_threshold is None else int(r.spreading_threshold)
                    ),
                    "config_hash": r.config_hash,
                    "memory_hash": r.memory_hash,
                    "created_at": r.created_at,
                    "capture_count": capture_counts.get(r.id, 0),
                    "action_count": action_counts.get(r.id, 0),
                }
                for r in runs
            ],
        }

    # ------------------------------------------------------------------
    # Captures
    # ------------------------------------------------------------------

    async def list_captures(self, session: AsyncSession, run_id: int) -> list[dict]:
        """What was captured for a Run, without the blobs.

        Deliberately excludes ``state``: a capture is hundreds of kilobytes and the
        listing exists to say *which* captures there are.  Fetching one is a separate
        request that renders it.
        """
        rows = (
            await session.execute(
                select(
                    RunStateCapture.id,
                    RunStateCapture.boundary,
                    RunStateCapture.codelet_count,
                    RunStateCapture.created_at,
                )
                .where(RunStateCapture.run_id == run_id)
                .order_by(RunStateCapture.codelet_count, RunStateCapture.id)
            )
        ).all()
        return [
            {
                "capture_id": r.id,
                "boundary": r.boundary,
                "codelet_count": r.codelet_count,
                "created_at": r.created_at,
            }
            for r in rows
        ]

    async def _capture_state(
        self, session: AsyncSession, run_id: int, boundary: str
    ) -> dict:
        if boundary not in BOUNDARIES:
            raise ReviewError(
                f"unknown boundary {boundary!r}; a Run is captured at {list(BOUNDARIES)}"
            )
        row = (
            await session.execute(
                select(RunStateCapture).where(
                    RunStateCapture.run_id == run_id,
                    RunStateCapture.boundary == boundary,
                )
            )
        ).scalars().first()
        if row is None:
            raise NotRecorded(
                f"run {run_id} has no {boundary!r} state capture; a Fast Run records "
                f"none, and a Run still in progress has not written its end capture yet"
            )
        return row.state

    async def get_capture(
        self, session: AsyncSession, run_id: int, boundary: str
    ) -> dict:
        """One recorded capture, in the shapes the live views already render."""
        state = await self._capture_state(session, run_id, boundary)
        projected = project_capture(state, self.meta)
        projected["run_id"] = run_id
        projected["boundary"] = boundary
        return projected

    async def get_raw_capture(
        self, session: AsyncSession, run_id: int, boundary: str
    ) -> dict:
        """The capture exactly as written.

        Kept because "the format is inspectable and versionable" is a claim WP3.4
        makes, and a claim nothing can look at is the failure this package exists to
        stop.  It is also what a bug report about a capture should be able to attach.
        """
        return await self._capture_state(session, run_id, boundary)

    # ------------------------------------------------------------------
    # Start against end
    # ------------------------------------------------------------------

    async def compare_run(self, session: AsyncSession, run_id: int) -> dict:
        """What changed between a Normal Run's two captures.

        Not both blobs side by side.  A Run-start capture and a Run-end capture are
        each a few hundred kilobytes and almost entirely identical — 59 Slipnet nodes,
        the same four strings, the same theme clusters — so serving both and letting
        the client diff them would move a megabyte to show a dozen facts.

        What is actually worth seeing is what the Run *did*: which structures it built,
        how far the temperature fell, which concepts it recruited, which themes came to
        dominate, and what it left in Episodic Memory for the next Run in the session.
        Those are computed here, straight from the two records, with no engine
        involved.
        """
        start = await self._capture_state(session, run_id, "start")
        end = await self._capture_state(session, run_id, "end")

        start_view = project_capture(start, self.meta)
        end_view = project_capture(end, self.meta)

        return {
            "run_id": run_id,
            "problem": end_view["problem"],
            "codelets": {
                "start": start_view["codelet_count"],
                "end": end_view["codelet_count"],
                "executed": end_view["codelet_count"] - start_view["codelet_count"],
            },
            "temperature": {
                "start": start_view["temperature"],
                "end": end_view["temperature"],
                "delta": round(
                    end_view["temperature"] - start_view["temperature"], 3
                ),
            },
            "structures": _structure_change(start_view["workspace"], end_view["workspace"]),
            "rules": {
                "top": end_view["workspace"]["top_rules"],
                "bottom": end_view["workspace"]["bottom_rules"],
            },
            "slipnet": _activation_movement(start_view["slipnet"], end_view["slipnet"]),
            "themes": _theme_movement(start_view["themespace"], end_view["themespace"]),
            "trace": {
                "events_at_start": len(start_view["trace"]),
                "events_at_end": len(end_view["trace"]),
                "by_type": _count_by(end_view["trace"], "event_type"),
                "events": end_view["trace"],
            },
            "memory": {
                "answers_at_start": len(start_view["memory"]["answers"]),
                "answers_at_end": len(end_view["memory"]["answers"]),
                "snags_at_start": len(start_view["memory"]["snags"]),
                "snags_at_end": len(end_view["memory"]["snags"]),
                # What this Run contributed to the Training Session it belongs to —
                # the one thing that survives a Run boundary.  Matched on the id
                # Episodic Memory stamps rather than on list position, because
                # positions coincide for reasons other than being the same answer.
                "added_answers": _added(
                    start_view["memory"]["answers"], end_view["memory"]["answers"],
                    "answer_id",
                ),
                "added_snags": _added(
                    start_view["memory"]["snags"], end_view["memory"]["snags"],
                    "snag_id",
                ),
            },
        }

    # ------------------------------------------------------------------
    # Audit actions
    # ------------------------------------------------------------------

    async def list_actions(
        self,
        session: AsyncSession,
        run_id: int,
        limit: int = 200,
        offset: int = 0,
        action_type: str | None = None,
        from_codelet: int | None = None,
    ) -> dict:
        """A page of the forward action log.

        Paginated because it has to be: a 2,000-codelet Audit Run records upwards of
        four thousand actions, and returning them all in one response is how a review
        surface becomes something nobody opens twice.  ``sequence`` is dense from 1
        within a Run, so an offset is also a position.
        """
        base = select(AuditAction).where(AuditAction.run_id == run_id)
        if action_type:
            base = base.where(AuditAction.action_type == action_type)
        if from_codelet is not None:
            base = base.where(AuditAction.codelet_count >= from_codelet)

        total = (
            await session.execute(
                select(func.count()).select_from(base.subquery())
            )
        ).scalar() or 0

        rows = (
            await session.execute(
                base.order_by(AuditAction.sequence).limit(limit).offset(offset)
            )
        ).scalars().all()

        return {
            "run_id": run_id,
            "total": total,
            "limit": limit,
            "offset": offset,
            "actions": [_action_dict(a) for a in rows],
        }

    async def action_summary(self, session: AsyncSession, run_id: int) -> dict:
        """Counts by action type, and the tick range the log covers."""
        rows = (
            await session.execute(
                select(
                    AuditAction.action_type,
                    func.count(),
                )
                .where(AuditAction.run_id == run_id)
                .group_by(AuditAction.action_type)
            )
        ).all()
        bounds = (
            await session.execute(
                select(
                    func.min(AuditAction.codelet_count),
                    func.max(AuditAction.codelet_count),
                    func.count(),
                ).where(AuditAction.run_id == run_id)
            )
        ).one()
        return {
            "run_id": run_id,
            "by_type": {t: c for t, c in rows},
            "first_codelet": bounds[0] or 0,
            "last_codelet": bounds[1] or 0,
            "total": bounds[2] or 0,
        }

    # ------------------------------------------------------------------
    # The Audit inspector — forward only
    # ------------------------------------------------------------------

    async def open_inspector(self, session: AsyncSession, run_id: int) -> dict:
        """Restore the Run-start capture and sit at tick 0.

        Opening an inspector on a Run that already has one restarts it, which is the
        only backwards movement offered: it is re-opening an inspection rather than
        scrubbing, and needs none of the action-inversion machinery WP3.8 deferred.
        """
        actions = await self.action_summary(session, run_id)
        if actions["total"] == 0:
            raise NotRecorded(
                f"run {run_id} recorded no audit actions; only a Run created in audit "
                f"mode can be stepped through"
            )
        state = await self._capture_state(session, run_id, "start")

        runner = EngineRunner(self.meta)
        problem = state["problem"]
        # ``init_mcat`` rebinds the Themespace every structure in the process
        # consults, so the binding is put back afterwards; see ``_themespace_binding``.
        with _themespace_binding():
            runner.init_mcat(
                problem["initial"],
                problem["modified"],
                problem["target"],
                problem["answer"],
                seed=state["rng"]["seed"],
            )
            try:
                restore_run_state(runner, state)
            except StateGraphError as exc:
                raise ReviewError(
                    f"the Run-start capture for run {run_id} could not be restored: {exc}"
                ) from None

        self._evict_if_needed()
        self._inspectors[run_id] = _Inspector(
            run_id=run_id,
            runner=runner,
            final_codelet_count=actions["last_codelet"],
        )
        return await self.inspector_state(session, run_id)

    async def advance_inspector(
        self, session: AsyncSession, run_id: int, to_codelet: int
    ) -> dict:
        """Step forward to ``to_codelet`` and report the state there.

        Re-execution rather than replay of the log: the log records what happened, and
        an Audit Run is serial and seeded, so running the restored engine forward
        *reproduces* it.  ``inspector_state`` then reports the recorded actions for the
        tick alongside the reconstructed state, which is what lets a reader see the two
        agree.
        """
        inspector = self._inspectors.get(run_id)
        if inspector is None:
            raise NotRecorded(
                f"no inspection open on run {run_id}; open one before stepping"
            )
        if to_codelet < inspector.position:
            raise BackwardsNotSupported(
                f"the inspector is at codelet {inspector.position} and cannot step back "
                f"to {to_codelet}: Phase 0 steps forward only. Re-open the inspection "
                f"to start again from the beginning."
            )

        target = min(to_codelet, inspector.final_codelet_count)
        runner = inspector.runner
        with _themespace_binding(runner.ctx.themespace):
            while runner.ctx.codelet_count < target:
                before = runner.ctx.codelet_count
                runner.step_mcat()
                if runner.ctx.codelet_count == before:
                    # The coderack emptied and reposting produced nothing — the
                    # recorded Run cannot be followed further, so stop rather than
                    # spin.
                    break
        inspector.last_used = time.monotonic()
        return await self.inspector_state(session, run_id)

    async def inspector_state(self, session: AsyncSession, run_id: int) -> dict:
        """Where the inspection is, and everything visible from there."""
        inspector = self._inspectors.get(run_id)
        if inspector is None:
            raise NotRecorded(f"no inspection open on run {run_id}")

        ctx = inspector.runner.ctx
        position = inspector.position

        actions = (
            await session.execute(
                select(AuditAction)
                .where(
                    AuditAction.run_id == run_id,
                    AuditAction.codelet_count == position,
                )
                .order_by(AuditAction.sequence)
            )
        ).scalars().all()

        codelet = next(
            (a for a in actions if a.action_type == "codelet"), None
        )
        changes = [a for a in actions if a.action_type.startswith("structure_")]

        return {
            "run_id": run_id,
            "codelet_count": position,
            "final_codelet_count": inspector.final_codelet_count,
            "at_end": position >= inspector.final_codelet_count,
            # The codelet whose execution produced this state.  ``on_codelet`` fires
            # after ``codelet_count`` is incremented, so the action recorded at tick N
            # is the N-th codelet, and this state is the one it left behind.
            "codelet": _action_dict(codelet) if codelet is not None else None,
            "structure_changes": [_action_dict(a) for a in changes],
            "actions": [_action_dict(a) for a in actions],
            "temperature": ctx.temperature.value,
            "recorded_temperature": (
                actions[0].temperature if actions else None
            ),
            "workspace": _live_workspace(ctx),
            "slipnet": _live_slipnet(ctx),
            "coderack": _live_coderack(ctx),
            "themespace": _live_themespace(ctx),
            "trace": _live_trace(ctx),
        }

    def close_inspector(self, run_id: int) -> bool:
        return self._inspectors.pop(run_id, None) is not None

    def _evict_if_needed(self) -> None:
        while len(self._inspectors) >= self.MAX_OPEN_INSPECTORS:
            oldest = min(self._inspectors.values(), key=lambda i: i.last_used)
            del self._inspectors[oldest.run_id]


# ─────────────────────────────────────────────────────────────────────────────
# Serialising a live inspector context
#
# The inspector holds a real runner, so it uses the same serializers the dashboard
# does — which is exactly why a projected capture has to match them (see
# ``tests/module/test_capture_projection.py``): both review surfaces feed the same
# React components, and they would disagree otherwise.
# ─────────────────────────────────────────────────────────────────────────────


def _live_workspace(ctx: Any) -> dict:
    from server.engine.serialization import serialize_workspace_state

    return serialize_workspace_state(ctx)


def _live_themespace(ctx: Any) -> dict:
    from server.engine.serialization import serialize_themespace_state

    return serialize_themespace_state(ctx)


def _live_slipnet(ctx: Any) -> dict:
    return {
        name: {
            "activation": node.activation,
            "conceptual_depth": node.conceptual_depth,
            "frozen": node.frozen,
        }
        for name, node in ctx.slipnet.nodes.items()
    }


def _live_coderack(ctx: Any) -> dict:
    return {
        "total_count": ctx.coderack.total_count,
        "type_counts": ctx.coderack.get_codelet_type_counts(),
    }


def _live_trace(ctx: Any) -> list[dict]:
    return [
        {
            "event_number": e.event_number,
            "event_type": e.event_type,
            "codelet_count": e.codelet_count,
            "temperature": e.temperature,
            "description": e.description or "",
            "theme_pattern": e.theme_pattern,
        }
        for e in ctx.trace.events
    ]


# ─────────────────────────────────────────────────────────────────────────────
# Comparison helpers
# ─────────────────────────────────────────────────────────────────────────────


def _action_dict(a: AuditAction) -> dict:
    return {
        "sequence": a.sequence,
        "codelet_count": a.codelet_count,
        "action_type": a.action_type,
        "temperature": a.temperature,
        "payload": a.payload,
        "before": a.before,
    }


def _added(before: list[dict], after: list[dict], id_key: str) -> list[dict]:
    """The entries present at the end that were not there at the start."""
    known = {row.get(id_key) for row in before}
    return [row for row in after if row.get(id_key) not in known]


def _count_by(rows: list[dict], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        counts[row[key]] = counts.get(row[key], 0) + 1
    return counts


def _structure_change(start: dict, end: dict) -> dict:
    """What the Run built, per string and per bridge kind.

    A Normal Run's start capture is taken before its first codelet, so in practice
    everything here is new — but it is computed as a difference rather than asserted to
    be one, because a start capture is not *required* to be empty and a comparison that
    assumed it was would quietly mislead the first time it was not.
    """
    def per_string(view: dict, key: str) -> dict[str, int]:
        return {text: len(items) for text, items in view[key].items()}

    def delta(a: dict[str, int], b: dict[str, int]) -> dict[str, int]:
        return {k: b.get(k, 0) - a.get(k, 0) for k in set(a) | set(b)}

    bonds_start, bonds_end = per_string(start, "bonds"), per_string(end, "bonds")
    groups_start, groups_end = per_string(start, "groups"), per_string(end, "groups")

    bridge_keys = ("top_bridges", "vertical_bridges", "bottom_bridges")
    rule_keys = ("top_rules", "bottom_rules")

    return {
        "bonds": {
            "start": bonds_start, "end": bonds_end,
            "built": delta(bonds_start, bonds_end),
        },
        "groups": {
            "start": groups_start, "end": groups_end,
            "built": delta(groups_start, groups_end),
        },
        "bridges": {
            "start": {k: len(start[k]) for k in bridge_keys},
            "end": {k: len(end[k]) for k in bridge_keys},
            "built": {k: len(end[k]) - len(start[k]) for k in bridge_keys},
        },
        "rules": {
            "start": {k: len(start[k]) for k in rule_keys},
            "end": {k: len(end[k]) for k in rule_keys},
            "built": {k: len(end[k]) - len(start[k]) for k in rule_keys},
        },
        # Counts only.  The bridges themselves, with their slippages, are in the
        # Run-end capture that the review renders beside this — repeating them here
        # would put the same structures in the response twice.
    }


#: How many moved concepts the comparison names.  The Slipnet has 59 nodes and most
#: barely stir; listing all of them buries the handful that carried the run.
_MOVEMENT_LIMIT = 15


def _activation_movement(start: dict, end: dict) -> dict:
    """Which concepts the Run recruited, biggest movers first."""
    moved = []
    for name, node in end.items():
        before = start.get(name, {}).get("activation", 0.0)
        after = node["activation"]
        if before == after:
            continue
        moved.append({
            "node": name,
            "start": before,
            "end": after,
            "delta": round(after - before, 3),
        })
    moved.sort(key=lambda m: abs(m["delta"]), reverse=True)
    return {
        "moved": moved[:_MOVEMENT_LIMIT],
        "moved_count": len(moved),
        "fully_active_at_start": sorted(
            n for n, v in start.items() if v["activation"] >= 100
        ),
        "fully_active_at_end": sorted(
            n for n, v in end.items() if v["activation"] >= 100
        ),
    }


def _theme_movement(start: dict, end: dict) -> dict:
    """Which themes came to characterise the Run's interpretation.

    Themes are the self-watching layer's own summary of what the Run decided, so the
    dominant ones at the end are the closest thing the record has to "what it thought
    it was doing" — worth surfacing above raw activation numbers.
    """
    def by_key(view: dict) -> dict[tuple[str, str, str | None], dict]:
        return {
            (c["theme_type"], c["dimension"], t["relation"]): t
            for c in view["clusters"]
            for t in c["themes"]
        }

    a, b = by_key(start), by_key(end)
    moved = []
    for key, theme in b.items():
        before = a.get(key, {}).get("activation", 0.0)
        if before == theme["activation"]:
            continue
        moved.append({
            "theme_type": key[0],
            "dimension": key[1],
            "relation": key[2],
            "start": before,
            "end": theme["activation"],
            "delta": round(theme["activation"] - before, 3),
            "dominant": theme["dominant"],
        })
    moved.sort(key=lambda m: abs(m["delta"]), reverse=True)
    return {
        "moved": moved[:_MOVEMENT_LIMIT],
        "moved_count": len(moved),
        "dominant_at_end": [
            {
                "theme_type": c["theme_type"],
                "dimension": c["dimension"],
                "relation": c["dominant_relation"],
            }
            for c in end["clusters"]
            if c["dominant_relation"] is not None
        ],
    }
