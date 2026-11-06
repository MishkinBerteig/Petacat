"""Reading back what the persistence modes wrote (WP3.9).

Normal and Audit exist to be looked at, and until this module there was nothing that
looked at them.  Phase 0's whole reason for retiring the old snapshot system was that
it wrote 230 MB across ten runs that no code path could read, so shipping the writers
without the readers would repeat the mistake exactly.

Three surfaces, three mechanisms
--------------------------------
- **The episodic-run timeline** is ordinary aggregate SQL over ``runs``,
  ``episodic_memory_clears``, ``run_state_captures`` and ``audit_actions``.  It is meant to
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

import json
import time
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from server.engine.hashing import config_hash
from server.engine.runner import EngineRunner
from server.engine.state_graph import StateGraphError, restore_run_state
from server.models.run import (
    AuditAction,
    Run,
    RunStateCapture,
    EpisodicMemoryClear,
)
from server.services.capture_projection import project_capture
from server.services.configuration_store import ConfigurationStore
from server.services.sinks import ACTION_INTERVENTION, AuditSink

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


class ReplayUnavailable(ReviewError):
    """The Run's configuration cannot be reconstructed, so no faithful replay exists.

    The inspector refuses with this rather than replaying under today's configuration and
    presenting the result as the Run.
    """


class BackwardsNotSupported(ReviewError):
    """The Audit inspector was asked to step back.  Phase 0 is forward-only."""


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
    #: What the replay was built from: ``_ConfigurationUse.as_dict()``.
    configuration: dict = field(default_factory=dict)
    #: A ``RunService`` holding only the replay, so a person's recorded action is applied
    #: by the same product method that applied it to the live run.
    host: Any = None
    #: What a person did, in order: ``(codelet_count, method, args)``; ``applied`` of them
    #: have been applied.
    interventions: list = field(default_factory=list)
    applied: int = 0
    #: The replay's own Audit record, built in memory only and never written.  It is compared,
    #: action for action, with the log the Run wrote; ``compared`` actions agree so far.
    sink: Any = None
    compared: int = 0
    #: The first place the replay and the record disagree, or ``None``.  Sticky.
    first_difference: dict | None = None
    last_used: float = field(default_factory=time.monotonic)

    @property
    def position(self) -> int:
        return self.runner.ctx.codelet_count if self.runner.ctx else 0


@dataclass
class _ConfigurationUse:
    """Which configuration a review surface is reading a Run under, and how it knows."""

    #: ``recorded`` (reconstructed at the Run's revision and proved by its hash) or
    #: ``current`` (it could not be, so today's is used and the surface says so).
    source: str
    provider: Any
    revision: int | None
    config_hash: str | None
    current_revision: int
    #: The global configuration has changed since the Run: it is not what is in use now.
    edited_since: bool | None
    reason: str | None = None

    def as_dict(self) -> dict:
        return {
            "source": self.source,
            "faithful": self.source == "recorded",
            "revision": self.revision,
            "config_hash": self.config_hash,
            "current_revision": self.current_revision,
            "edited_since": self.edited_since,
            "reason": self.reason,
        }


def _overrides_of(base: Any, captured: dict | None) -> dict:
    """The parameters a Run overrode: those of its start capture that differ from *base*.

    The capture holds every parameter the Run resolved, but as JSONB, which reorders the
    keys of a dictionary-valued parameter, and a dictionary's order is behaviour (it is
    part of the configuration hash).  Laying the whole capture over the configuration
    would replace the right order with a scrambled one, so only a value that really differs
    (by value and by number type) is taken from it.
    """
    out = {}
    for name, value in (captured or {}).items():
        have = base.params.get(name, _MISSING)
        if have is _MISSING or type(have) is not type(value) or have != value:
            out[name] = value
    return out


_MISSING = object()


def _json_normal(value: Any) -> Any:
    """What a value reads back as from the JSON column (tuples become lists, and so on)."""
    return json.loads(json.dumps(value))


def clear_summary(clear: EpisodicMemoryClear) -> dict:
    """The wire shape of one Episodic Memory clear (``MemoryClear``)."""
    return {
        "clear_id": clear.id,
        "cleared_at": clear.cleared_at,
        "after_run_id": clear.after_run_id,
        "note": clear.note or "",
    }


class ReviewService:
    """Reads the record; never mutates a Run.

    Given the ``ConfigurationStore`` rather than the ``RunService`` on purpose: review
    must work for Runs whose runner is long gone, which is nearly all of them, so it
    has no business consulting the live-run registry.  What it needs the metadata for
    is the short names and conceptual depths a capture references by name, and the
    Slipnet a restored inspector runs against.
    """

    #: How many inspections may be held open at once.  Each holds a full engine, so
    #: this is a memory bound; the least recently used is dropped when it is exceeded.
    MAX_OPEN_INSPECTORS = 3

    def __init__(self, store: Any) -> None:
        self._store = store
        self._inspectors: dict[int, _Inspector] = {}

    # ------------------------------------------------------------------
    # The configuration a Run used
    # ------------------------------------------------------------------

    async def run_configuration(
        self, session: AsyncSession, run_id: int, state: dict | None
    ) -> _ConfigurationUse:
        """The configuration Run ``run_id`` executed under, reconstructed and proved.

        A Run names its configuration with ``configuration_revision`` (the global
        configuration's revision when it was created) and ``config_hash``.  The journal
        reconstructs the configuration at that revision; the Run's own parameters (the
        whole set it resolved, in its start capture) are laid over it as the Run laid its
        overrides; and the result must hash to the Run's ``config_hash``.  When any step
        fails the answer says ``source = "current"`` with the reason, and today's
        configuration is returned only so that record-based displays have something to
        label with.  A caller that replays must refuse in that case.
        """
        row = (
            await session.execute(select(Run).where(Run.id == run_id))
        ).scalars().first()
        current = self._store.current()
        current_revision = self._store.revision

        def fallback(reason: str) -> _ConfigurationUse:
            return _ConfigurationUse(
                "current", current,
                row.configuration_revision if row is not None else None,
                row.config_hash if row is not None else None,
                current_revision, None, reason,
            )

        if row is None:
            return fallback(f"run {run_id} has no recorded row")
        if row.configuration_revision is None:
            return fallback(
                "the Run was recorded before the configuration revision was kept, so the "
                "configuration it used cannot be named"
            )
        if row.config_hash is None:
            return fallback("the Run recorded no configuration hash to check a reconstruction against")
        try:
            view = await self._store.provider(session, revision=row.configuration_revision)
        except Exception as exc:  # the journal cannot reach that revision
            return fallback(
                f"the global configuration at revision {row.configuration_revision} could "
                f"not be reconstructed from the journal: {exc}"
            )
        provider = view.provider.with_overrides(
            _overrides_of(view.provider, (state or {}).get("parameters"))
        )
        rebuilt = config_hash(provider)
        if rebuilt != row.config_hash:
            return fallback(
                f"the configuration reconstructed at revision {row.configuration_revision} "
                f"hashes to {rebuilt}, not to the {row.config_hash} the Run recorded; the "
                f"global configuration was changed in a way the journal does not hold"
            )
        return _ConfigurationUse(
            "recorded", provider, row.configuration_revision, row.config_hash,
            current_revision, view.config_hash != config_hash(current),
        )

    async def _projection_meta(
        self, session: AsyncSession, run_id: int, state: dict
    ) -> tuple[Any, dict]:
        """What to project a capture with: the Run's own configuration where it can be proved."""
        use = await self.run_configuration(session, run_id, state)
        return use.provider, use.as_dict()

    # ------------------------------------------------------------------
    # The episodic-run timeline
    # ------------------------------------------------------------------

    async def episodic_timeline(
        self, session: AsyncSession, limit: int = 50, offset: int = 0
    ) -> dict:
        """Recorded episodic runs, newest first, with Episodic Memory clears in place.

        ``limit`` and ``offset`` count *runs*.  A clear with ``after_run_id = a`` sits
        above every run with id <= a and below every run with id > a, so the list reads
        ``[clears a >= r1], r1, [clears r2 <= a < r1], r2, ...`` for a page of runs
        ``r1 > r2 > ...``.  A clear belongs to the page where ``rk <= a < prev``, ``rk``
        being the page's oldest run and ``prev`` the run just before the page (infinity
        on page 0), so the pages partition the clears.  On the last page the lower bound
        is dropped: clears with a null ``after_run_id``, or placed below the oldest run
        (because that run was deleted), come at the very end.  Clears in the same gap are
        newest first.

        The placement is by run id, never by clock, so ties cannot misplace a marker.
        Counts are aggregated per run in the same pass rather than queried per row.
        """
        total_runs = (
            await session.execute(select(func.count()).select_from(Run))
        ).scalar() or 0
        total_clears = (
            await session.execute(
                select(func.count()).select_from(EpisodicMemoryClear)
            )
        ).scalar() or 0

        runs = (
            await session.execute(
                select(Run).order_by(Run.id.desc()).limit(limit).offset(offset)
            )
        ).scalars().all()
        run_ids = [r.id for r in runs]

        capture_counts: dict[int, int] = {}
        action_counts: dict[int, int] = {}
        if run_ids:
            capture_counts = dict(
                (
                    await session.execute(
                        select(RunStateCapture.run_id, func.count())
                        .where(RunStateCapture.run_id.in_(run_ids))
                        .group_by(RunStateCapture.run_id)
                    )
                ).all()
            )
            action_counts = dict(
                (
                    await session.execute(
                        select(AuditAction.run_id, func.count())
                        .where(AuditAction.run_id.in_(run_ids))
                        .group_by(AuditAction.run_id)
                    )
                ).all()
            )

        prev: int | None = None  # None = infinity: nothing newer than this page
        if offset > 0:
            prev = (
                await session.execute(
                    select(Run.id).order_by(Run.id.desc()).limit(1).offset(offset - 1)
                )
            ).scalar()
        is_last_page = offset + len(runs) >= total_runs

        # The clears table is small (one row per deliberate clear), so the placement
        # rules are applied here, where they can be read, rather than in SQL.
        all_clears = (
            await session.execute(
                select(EpisodicMemoryClear).order_by(EpisodicMemoryClear.id.desc())
            )
        ).scalars().all()

        def on_page(c: EpisodicMemoryClear) -> bool:
            if not runs:
                return offset == 0  # no runs at all: every clear is on page 0
            a = c.after_run_id
            if a is None:
                return is_last_page
            if prev is not None and a >= prev:
                return False
            return is_last_page or a >= run_ids[-1]

        clears = [c for c in all_clears if on_page(c)]

        items: list[dict] = []
        pending = list(clears)  # newest first
        for run in runs:
            above, pending = (
                [c for c in pending if c.after_run_id is not None and c.after_run_id >= run.id],
                [c for c in pending if c.after_run_id is None or c.after_run_id < run.id],
            )
            items.extend({"kind": "memory_cleared", "clear": clear_summary(c)} for c in above)
            items.append(
                {
                    "kind": "run",
                    "run": {
                        "run_id": run.id,
                        "mode": run.mode or "normal",
                        "status": run.status or "",
                        "initial": run.initial_string,
                        "modified": run.modified_string,
                        "target": run.target_string,
                        "answer": run.answer_string,
                        "justify_mode": bool(run.justify_mode),
                        "seed": run.seed,
                        "codelet_count": run.codelet_count or 0,
                        "temperature": run.temperature or 0.0,
                        "spreading_threshold": int(run.spreading_threshold),
                        "config_hash": run.config_hash,
                        "configuration_revision": run.configuration_revision,
                        "memory_hash": run.memory_hash,
                        "created_at": run.created_at,
                        "capture_count": capture_counts.get(run.id, 0),
                        "action_count": action_counts.get(run.id, 0),
                    },
                }
            )
        items.extend({"kind": "memory_cleared", "clear": clear_summary(c)} for c in pending)

        return {
            "items": items,
            "total_runs": total_runs,
            "total_clears": total_clears,
            "limit": limit,
            "offset": offset,
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
        meta, used = await self._projection_meta(session, run_id, state)
        projected = project_capture(state, meta)
        projected["configuration"] = used
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
        dominate, and what it left in Episodic Memory for the next episodic run.
        Those are computed here, straight from the two records, with no engine
        involved.
        """
        start = await self._capture_state(session, run_id, "start")
        end = await self._capture_state(session, run_id, "end")

        meta, used = await self._projection_meta(session, run_id, end)
        start_view = project_capture(start, meta)
        end_view = project_capture(end, meta)

        return {
            "run_id": run_id,
            "configuration": used,
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
            "slipnet": _activation_movement(
                start_view["slipnet"], end_view["slipnet"], meta.get_param("max_activation")
            ),
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
                # What this Run contributed to the Episodic Memory —
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
        """Restore the Run-start capture and sit at tick 0, under the Run's own configuration.

        Opening an inspector on a Run that already has one restarts it, which is the
        only backwards movement offered: it is re-opening an inspection rather than
        scrubbing, and needs none of the action-inversion machinery WP3.8 deferred.

        The replay is the Run, not a new run of the same problem.  It executes under the
        configuration the Run used (reconstructed from the journal at the Run's recorded
        revision, and proved by ``config_hash``), and applies what a person did to the live
        Run (clamps, Undo, threshold changes, ...), at the codelet each happened at, through
        the same ``RunService`` methods.  When the configuration cannot be reconstructed it
        raises :class:`ReplayUnavailable`; it never replays under today's configuration.
        While stepping it checks every action it produces against the log the Run wrote and
        reports the first disagreement (``replay`` in the state).
        """
        actions = await self.action_summary(session, run_id)
        if actions["total"] == 0:
            raise NotRecorded(
                f"run {run_id} recorded no audit actions; only a Run created in audit "
                f"mode can be stepped through"
            )
        state = await self._capture_state(session, run_id, "start")
        use = await self.run_configuration(session, run_id, state)
        if use.source != "recorded":
            raise ReplayUnavailable(
                f"run {run_id} cannot be replayed faithfully: {use.reason}. Its recorded "
                f"actions and captures are still available."
            )

        from server.services.run_service import RunService

        # ``use.provider`` is the Run's own: its configuration at its revision with its
        # parameter overrides laid over it.
        runner = EngineRunner(use.provider)
        problem = state["problem"]
        sink = AuditSink()  # in memory only: never flushed, it is what the replay is checked with
        # The inspector's runner binds its own run (its provider, constants and
        # Themespace) whenever it executes, so opening or stepping it cannot touch a live
        # run; nothing here swaps a process-wide binding.
        runner.init_mcat(
            problem["initial"],
            problem["modified"],
            problem["target"],
            problem["answer"],
            seed=state["rng"]["seed"],
            sink=sink,
        )
        try:
            restore_run_state(runner, state)
        except StateGraphError as exc:
            raise ReviewError(
                f"the Run-start capture for run {run_id} could not be restored: {exc}"
            ) from None

        # The host's configuration is the Run's, so a method that reads the service's
        # configuration (the codelet-pattern clamps) reads the Run's.
        host = RunService(ConfigurationStore(use.provider, use.revision or 0))
        host._runners[run_id] = runner
        rows = (
            await session.execute(
                select(AuditAction)
                .where(
                    AuditAction.run_id == run_id,
                    AuditAction.action_type == ACTION_INTERVENTION,
                )
                .order_by(AuditAction.sequence)
            )
        ).scalars().all()

        self._evict_if_needed()
        inspector = _Inspector(
            run_id=run_id,
            runner=runner,
            final_codelet_count=actions["last_codelet"],
            configuration=use.as_dict(),
            host=host,
            interventions=[
                (r.codelet_count, r.payload["method"], r.payload.get("args", {})) for r in rows
            ],
            sink=sink,
        )
        self._inspectors[run_id] = inspector
        self._apply_due(inspector)
        await self._compare(session, inspector)
        return await self.inspector_state(session, run_id)

    def _apply_due(self, inspector: _Inspector, before_a_step: bool = False) -> None:
        """Apply every recorded action of a person that happened at or before this codelet.

        A restore that a Step or a Run made as it started (``before_a_drive``) belongs to the
        moment before the run's next codelet, so it waits for that: the person saw the moment
        still on show at the codelet where it was put away.
        """
        count = inspector.position
        while inspector.applied < len(inspector.interventions):
            at, method, args = inspector.interventions[inspector.applied]
            if at > count:
                break
            if args.get("before_a_drive") and not before_a_step:
                break
            inspector.applied += 1
            try:
                if "unrecordable" in args:
                    raise ValueError("the action's arguments could not be recorded")
                if method == "finish":
                    inspector.runner.finish()
                else:
                    if method == "_display_over_themespace":
                        args = {**args, "key": tuple(args["key"])}
                    getattr(inspector.host, method)(inspector.run_id, **args)
            except Exception as exc:
                self._note_difference(
                    inspector, at, "an action of the person could not be applied again",
                    f"{method}({args})", f"{type(exc).__name__}: {exc}",
                )

    @staticmethod
    def _note_difference(inspector: _Inspector, tick: int, what: str, recorded: Any, replayed: Any):
        if inspector.first_difference is None:
            inspector.first_difference = {
                "tick": tick, "what": what, "recorded": recorded, "replayed": replayed,
            }

    async def _compare(self, session: AsyncSession, inspector: _Inspector) -> None:
        """Check what the replay did since the last check against the log the Run wrote.

        Every codelet, structure change, trace event and answer: its type, codelet count,
        temperature and payload.  The first disagreement is kept; nothing after it is
        trusted, so comparison stops there.
        """
        if inspector.first_difference is not None:
            return
        replayed = inspector.sink._actions[inspector.compared:]
        recorded = (
            await session.execute(
                select(AuditAction)
                .where(
                    AuditAction.run_id == inspector.run_id,
                    AuditAction.action_type != ACTION_INTERVENTION,
                    AuditAction.codelet_count <= inspector.position,
                )
                .order_by(AuditAction.sequence)
                .offset(inspector.compared)
            )
        ).scalars().all()
        for rec, rep in zip(recorded, replayed):
            a = (rec.action_type, rec.codelet_count, rec.temperature, rec.payload)
            b = (rep.action_type, rep.codelet_count, rep.temperature, _json_normal(rep.payload))
            if a != b:
                self._note_difference(
                    inspector, rec.codelet_count,
                    f"the replayed {rep.action_type} differs from the recorded {rec.action_type}",
                    {"action_type": rec.action_type, "temperature": rec.temperature, "payload": rec.payload},
                    {"action_type": rep.action_type, "temperature": rep.temperature, "payload": b[3]},
                )
                return
            inspector.compared += 1
        matched = min(len(recorded), len(replayed))
        if len(replayed) > len(recorded):
            self._note_difference(
                inspector, inspector.position,
                "the replay produced an action the Run did not record",
                inspector.compared - matched + len(recorded),
                inspector.compared - matched + len(replayed),
            )
            return
        # The engine hands the sink some events (a structure built by the codelet just run)
        # at the start of the next step, stamped with this codelet's count.  So the log can
        # hold actions of this very codelet that the replay emits one step later; anything
        # from an earlier codelet must already be there.
        lagging = recorded[len(replayed):]
        if any(a.codelet_count < inspector.position for a in lagging):
            self._note_difference(
                inspector, min(a.codelet_count for a in lagging),
                "the Run recorded an action the replay did not produce",
                {"action_type": lagging[0].action_type, "payload": lagging[0].payload},
                None,
            )

    async def advance_inspector(
        self, session: AsyncSession, run_id: int, to_codelet: int
    ) -> dict:
        """Step forward to ``to_codelet`` and report the state there.

        Re-execution rather than replay of the log: the log records what happened, and
        an Audit Run is serial and seeded, so running the restored engine forward under the
        Run's own configuration, applying what a person did at the codelets they did it,
        *reproduces* it.  Each step is then checked against the log (``_compare``), and
        ``inspector_state`` reports the result, so a reader sees whether the two agree.
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
        while runner.ctx.codelet_count < target:
            before = runner.ctx.codelet_count
            self._apply_due(inspector, before_a_step=True)
            runner.step_mcat()
            if runner.ctx.codelet_count == before:
                # The coderack emptied and reposting produced nothing — the
                # recorded Run cannot be followed further, so stop rather than
                # spin.
                break
            self._apply_due(inspector)
        await self._compare(session, inspector)
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

        # Read inside the inspector's own run: the views compute from its structures.
        with ctx.scope():
            live = {
                "workspace": _live_workspace(ctx),
                "slipnet": _live_slipnet(ctx),
                "coderack": _live_coderack(ctx),
                "eeg": ctx.eeg.history(),
                "themespace": _live_themespace(ctx),
                "trace": _live_trace(ctx),
            }

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
            # Whether this is the Run: the configuration it was rebuilt under, how many of the
            # person's actions have been applied again, and the first place (if any) the
            # replay and the record disagree.  ``faithful`` is false from that place on.
            "replay": {
                "faithful": inspector.first_difference is None,
                "first_difference": inspector.first_difference,
                "checked_actions": inspector.compared,
                "interventions_applied": inspector.applied,
                "interventions_total": len(inspector.interventions),
                "configuration": inspector.configuration,
            },
            **live,
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
    from server.engine.coderack import coderack_display

    return coderack_display(
        ctx.coderack, ctx.temperature.value, ctx.last_codelet_type
    )


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


def _activation_movement(start: dict, end: dict, full: float) -> dict:
    """Which concepts the Run recruited, biggest movers first.  *full* is the activation
    ceiling (``max_activation``): a concept at it is fully active."""
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
            n for n, v in start.items() if v["activation"] >= full
        ),
        "fully_active_at_end": sorted(
            n for n, v in end.items() if v["activation"] >= full
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
