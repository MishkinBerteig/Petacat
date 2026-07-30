"""RunService — orchestrates engine execution with DB persistence.

Creates runs, steps codelets, persists snapshots, manages lifecycle.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from server.engine.memory import AnswerDescription, EpisodicMemory, SnagDescription
from server.engine.metadata import MetadataProvider
from server.engine.runner import EngineContext, EngineRunner, STATUS_ANSWER_FOUND, STATUS_HALTED, STATUS_PAUSED, STATUS_RUNNING, StepResult
from server.engine.serialization import serialize_themespace_state, serialize_workspace_state
from server.engine.trace import SNAG
from server.models.run import (
    _utcnow,
    AnswerDescriptionRow,
    AuditAction,
    CycleSnapshot,
    Run,
    RunStateCapture,
    SnagDescriptionRow,
    TraceEventRow,
    TrainingSession,
)
from server.engine.commentary import CommentaryLog, DiscardingCommentaryLog
from server.engine.free_running import FreeRunningEngine
from server.engine.hashing import config_hash, memory_hash
from server.engine.parameters import resolved_parameters, validate_overrides
from server.services.sinks import MODE_AUDIT, MODE_FAST, MODE_NORMAL, sink_for_mode


# Shared cross-run episodic memory (per-process)
_global_memory = EpisodicMemory()


def _live_answer_fields(problem: Any, top_rule_description: str) -> dict:
    """The parts of an answer description that live only in memory.

    Reminding activation, the per-type theme patterns, the unjustified-theme
    pattern and the coherence verdict (§4.7.1, §4.7.3, §4.7.5) are computed as
    answers are found and compared, so they are read from the in-memory Episodic
    Memory rather than the persisted row.

    Matched on the problem and rule rather than on an id: the database row's
    ``id`` and ``AnswerDescription.answer_id`` come from independent counters, so
    comparing them silently never matched and every answer was served with these
    fields missing.
    """
    key = (tuple(problem or ()), top_rule_description or "")
    for a in _global_memory.answers:
        if (tuple(a.problem), a.top_rule_description or "") == key:
            return {
                "activation": a.activation,
                "top_themes": a.top_themes,
                "vertical_themes": a.vertical_themes,
                "bottom_themes": a.bottom_themes,
                "unjustified_themes": a.unjustified_themes,
                "top_rule_abstractness": a.top_rule_abstractness,
                "is_coherent": a.is_coherent,
            }
    return {}


@dataclass
class RunInfo:
    run_id: int
    status: str
    codelet_count: int
    temperature: float
    initial: str
    modified: str
    target: str
    answer: str | None
    #: True when the answer was *given* at creation for the engine to justify,
    #: rather than discovered by it. Both arrive in ``answer``, so without this
    #: a display cannot tell "it found xyd" from "it was asked about xyd".
    justify_mode: bool = False
    #: Which Slipnet nodes were allowed to spread (0-100; 100 = the original).
    #: Part of the run's identity: a run at any other value is not comparable
    #: with the dissertation's results.
    spreading_threshold: int = 100
    #: The persistence mode this run was created with.
    mode: str = "normal"


class RunService:
    """Orchestrates engine + DB persistence."""

    def __init__(self, meta: MetadataProvider) -> None:
        self.meta = meta
        self._runners: dict[int, EngineRunner] = {}
        #: The sink attached to each live run.  Persistence mode is a property of a
        #: run, not a global setting, so this is per-run rather than per-service.
        self._sinks: dict[int, Any] = {}
        #: Mode per live run, so the service knows which runs must not be written to.
        self._modes: dict[int, str] = {}
        #: Worker count per live run.  1 is the serial loop — the permanent reference
        #: mode — and is the default, so nothing changes unless a run asks for it.
        self._workers: dict[int, int] = {}
        #: Last free-running telemetry per run — worker count, conflict rate, throughput.
        self._free_run_telemetry: dict[int, dict] = {}
        #: Identifiers for Fast Runs.  A Fast Run has no database row to take an id
        #: from — that is the whole point — so it needs one from somewhere, and it must
        #: not collide with a real ``runs.id``.  Negative numbers cannot: the column is
        #: a positive autoincrement.
        self._next_fast_id: int = -1
        # Per-runner control state
        self._breakpoints: dict[int, int | None] = {}
        self._step_sizes: dict[int, int] = {}
        self._stop_flags: dict[int, bool] = {}

    # ------------------------------------------------------------------
    # Existing methods
    # ------------------------------------------------------------------

    async def create_run(
        self,
        session: AsyncSession,
        initial: str,
        modified: str,
        target: str,
        answer: str | None = None,
        seed: int = 0,
        spreading_threshold: int | None = None,
        mode: str = MODE_NORMAL,
        workers: int = 1,
        parameters: dict[str, Any] | None = None,
    ) -> RunInfo:
        """Create a new run and initialise the engine.

        ``mode`` is a property of *this run*, not a global setting, because later
        phases want a Fast corpus-training population and a Normal live dialogue in the
        same process.  It selects a sink and nothing else: the engine is handed the
        same problem, the same seed and the same memory whichever mode is chosen, which
        is what makes a mode-mixed Training Session comparable with an all-Fast one.

        ``workers`` above 1 runs the Run free-running (WP4.4): codelets across CPU
        cores with no global barrier.  It defaults to 1 — the serial loop — because
        serial execution is the permanent reference mode every later phase validates
        against, and because free-running is a *different draw*: the expected range is
        unchanged, but a given seed no longer reproduces a given run, since execution
        order is not determined.  Audit refuses it outright, for the same reason it
        exists: a record of actions with no record of commit order reconstructs nothing.
        """
        # Validated before anything is created, so a bad override cannot leave a
        # half-built Run behind. Raises ValueError, which the API turns into a 400.
        overrides = validate_overrides(parameters)
        run_meta = self.meta.with_overrides(overrides)

        workers = max(1, int(workers))
        if workers > 1 and mode == MODE_AUDIT:
            raise ValueError(
                "Audit mode is serial by definition and cannot run free-running: it "
                "reconstructs intermediate states by replaying its action log forward, "
                "and under free-running the order that log records is not the order "
                "things happened in. Use Normal or Fast for a parallel run."
            )
        threshold = (
            run_meta.get_param("spreading_activation_threshold", 100)
            if spreading_threshold is None
            else max(0, min(100, spreading_threshold))
        )
        # The explicit argument and the parameter are the same setting reached two ways,
        # so the stored parameter set has to agree with what the Run actually used.
        overrides["spreading_activation_threshold"] = threshold
        run_meta = self.meta.with_overrides(overrides)
        if mode == MODE_FAST:
            return self._create_fast_run(
                initial, modified, target, answer, seed, threshold, workers, overrides,
            )

        run = Run(
            initial_string=initial,
            modified_string=modified,
            target_string=target,
            answer_string=answer,
            seed=seed,
            status="initialized",
            justify_mode=answer is not None,
            spreading_threshold=threshold,
            mode=mode,
            session_id=await self._current_session_id(session),
            # Hashed over the Run's *own* metadata, so two Runs that differ only in a
            # parameter override are distinguishable by their config hash alone.
            config_hash=config_hash(run_meta),
            parameters=resolved_parameters(run_meta),
            # Hashed *before* the run executes: it identifies the memory the run
            # inherited, not the one it leaves behind.
            memory_hash=memory_hash(
                EpisodicMemory() if mode == MODE_FAST else _global_memory
            ),
        )
        session.add(run)
        await session.flush()

        sink = sink_for_mode(mode)
        # A Fast Run gets an ephemeral memory of its own rather than the shared one:
        # its whole point is that it leaves nothing behind, and contributing answers to
        # the Training Session's memory would be leaving something behind.  It also
        # discards commentary, which no part of cognition reads back.
        memory = EpisodicMemory() if mode == MODE_FAST else _global_memory
        commentary = DiscardingCommentaryLog() if mode == MODE_FAST else CommentaryLog()

        runner = EngineRunner(self.meta)
        runner.init_mcat(initial, modified, target, answer=answer, seed=seed,
                         memory=memory, sink=sink, commentary=commentary,
                         parameters=overrides)
        self._sinks[run.id] = sink
        # Set before the first codelet runs, so the whole run uses it.
        runner.ctx.spreading_activation_threshold = threshold
        self._runners[run.id] = runner
        self._modes[run.id] = mode
        self._workers[run.id] = workers

        await session.commit()

        return RunInfo(
            run_id=run.id,
            status="initialized",
            codelet_count=0,
            temperature=runner.ctx.temperature.value,
            initial=initial,
            modified=modified,
            target=target,
            answer=answer,
            justify_mode=answer is not None,
            spreading_threshold=threshold,
            mode=mode,
        )

    def _create_fast_run(
        self,
        initial: str,
        modified: str,
        target: str,
        answer: str | None,
        seed: int,
        threshold: int,
        workers: int = 1,
        parameters: dict[str, Any] | None = None,
    ) -> RunInfo:
        """A Fast Run, created without touching the database.

        Not "created and then not written to" — the session is never used, no row is
        inserted, and no identifier is taken from one.  Fast Run's requirement is zero
        database activity *during the run and at its end*, and creation is part of that:
        a run that inserted a row and then wrote nothing more would still fail with the
        database stopped, which is the condition the mode is verified under.

        The memory is ephemeral and the commentary is discarded, so the run leaves
        nothing behind in the process either.
        """
        run_id = self._next_fast_id
        self._next_fast_id -= 1

        sink = sink_for_mode(MODE_FAST)
        runner = EngineRunner(self.meta)
        runner.init_mcat(
            initial, modified, target, answer=answer, seed=seed,
            memory=EpisodicMemory(), sink=sink,
            commentary=DiscardingCommentaryLog(), parameters=parameters,
        )
        runner.ctx.spreading_activation_threshold = threshold

        self._runners[run_id] = runner
        self._sinks[run_id] = sink
        self._modes[run_id] = MODE_FAST
        self._workers[run_id] = workers

        return RunInfo(
            run_id=run_id,
            status="initialized",
            codelet_count=0,
            temperature=runner.ctx.temperature.value,
            initial=initial,
            modified=modified,
            target=target,
            answer=answer,
            justify_mode=answer is not None,
            spreading_threshold=threshold,
            mode=MODE_FAST,
        )

    def _is_fast(self, run_id: int) -> bool:
        return self._modes.get(run_id) == MODE_FAST

    async def _current_session_id(self, session: AsyncSession) -> int:
        """The open Training Session, opening one if none is.

        Sessions are not created by the user; they are the span between memory clears,
        which is already how the concept worked.  This gives that span a row so Runs can
        be grouped and reviewed (WP3.0), and changes no behaviour.
        """
        result = await session.execute(
            select(TrainingSession)
            .where(TrainingSession.ended_at.is_(None))
            .order_by(TrainingSession.id.desc())
            .limit(1)
        )
        current = result.scalars().first()
        if current is None:
            current = TrainingSession()
            session.add(current)
            await session.flush()
        return current.id

    async def step(
        self,
        session: AsyncSession,
        run_id: int,
        n: int = 1,
    ) -> list[StepResult]:
        """Step N codelets, persisting snapshots at cycle boundaries."""
        runner = self._runners.get(run_id)
        if runner is None:
            raise ValueError(f"Run {run_id} not found or not loaded")

        results = []

        # The loop is pure engine work now.  Persistence is the attached sink's
        # business: it buffers as the engine emits and is written once, below.  What
        # used to be here was an ``await`` per codelet whose trace slice was empty
        # about 99.2% of the time, and a full ~43 KB snapshot every fifteenth codelet
        # that nothing could read back (defect D1).
        for _ in range(n):
            step_result = runner.step_mcat()
            results.append(step_result)

            # Stop stepping if an answer was found, or if the run gave up
            if step_result.answer_found or step_result.gave_up:
                break

        if self._is_fast(run_id):
            # No flush, no row update, no commit.  A Fast Run must complete with the
            # database stopped, so the session is not touched even to say the run moved.
            return results

        await self._flush_sink(session, run_id)

        # Update run row — include answer_string if found
        update_values: dict = {
            "codelet_count": runner.ctx.codelet_count,
            "temperature": runner.ctx.temperature.value,
            "status": runner.status,
        }
        if runner.ctx.workspace.answer_string is not None:
            update_values["answer_string"] = runner.ctx.workspace.answer_string.text

        await session.execute(
            update(Run)
            .where(Run.id == run_id)
            .values(**update_values)
        )
        await session.commit()
        return results

    async def get_run_info(self, session: AsyncSession, run_id: int) -> RunInfo | None:
        """Get current run info, live where a runner is loaded.

        ``run_to_completion`` writes ``codelet_count`` and ``temperature`` back to
        the row only when the run ends, so mid-run the row still holds the values
        it was created with — status ``running`` but 0 codelets and temperature
        100.  Serving those made this endpoint actively misleading: a UI polling
        it during a run saw the temperature jump to 100 on every sample (before a
        live read corrected it a moment later) and a codelet count stuck at 0.

        A loaded runner is the authority on how far a run has actually got, so
        prefer it and fall back to the row for runs not currently in memory.
        """
        runner = self._runners.get(run_id)

        if self._is_fast(run_id):
            # A Fast Run has no row to read.  It is still fully observable — "Fast"
            # means not written down, not unobservable — so it is served entirely from
            # the live runner.
            if runner is None or runner.ctx is None:
                return None
            ws = runner.ctx.workspace
            return RunInfo(
                run_id=run_id,
                status=runner.status,
                codelet_count=runner.ctx.codelet_count,
                temperature=runner.ctx.temperature.value,
                initial=ws.initial_string.text,
                modified=ws.modified_string.text,
                target=ws.target_string.text,
                answer=ws.answer_string.text if ws.answer_string else None,
                justify_mode=runner.ctx.justify_mode,
                spreading_threshold=runner.ctx.spreading_activation_threshold,
                mode=MODE_FAST,
            )

        result = await session.execute(select(Run).where(Run.id == run_id))
        run = result.scalar_one_or_none()
        if run is None:
            return None

        if runner is not None and runner.ctx is not None:
            answer_string = runner.ctx.workspace.answer_string
            return RunInfo(
                run_id=run.id,
                status=runner.status,
                codelet_count=runner.ctx.codelet_count,
                temperature=runner.ctx.temperature.value,
                initial=run.initial_string,
                modified=run.modified_string,
                target=run.target_string,
                answer=answer_string.text if answer_string is not None else None,
                justify_mode=bool(run.justify_mode),
                spreading_threshold=int(
                    getattr(runner.ctx, "spreading_activation_threshold",
                            run.spreading_threshold)
                ),
                mode=run.mode or MODE_NORMAL,
            )

        return RunInfo(
            run_id=run.id,
            status=run.status,
            codelet_count=run.codelet_count,
            temperature=run.temperature,
            initial=run.initial_string,
            modified=run.modified_string,
            target=run.target_string,
            answer=run.answer_string,
            justify_mode=bool(run.justify_mode),
            spreading_threshold=(
                100 if run.spreading_threshold is None else int(run.spreading_threshold)
            ),
        )

    def get_runner(self, run_id: int) -> EngineRunner | None:
        return self._runners.get(run_id)

    def get_workspace_state(self, run_id: int) -> dict | None:
        """Get current workspace state as a dict."""
        runner = self._runners.get(run_id)
        if runner is None or runner.ctx is None:
            return None
        return serialize_workspace_state(runner.ctx)

    def get_slipnet_state(self, run_id: int) -> dict | None:
        """Get current slipnet activations."""
        runner = self._runners.get(run_id)
        if runner is None or runner.ctx is None:
            return None
        return {
            name: {
                "activation": node.activation,
                "conceptual_depth": node.conceptual_depth,
                "frozen": node.frozen,
            }
            for name, node in runner.ctx.slipnet.nodes.items()
        }

    def get_coderack_state(self, run_id: int) -> dict | None:
        """Get current coderack contents."""
        runner = self._runners.get(run_id)
        if runner is None or runner.ctx is None:
            return None
        return {
            "total_count": runner.ctx.coderack.total_count,
            "type_counts": runner.ctx.coderack.get_codelet_type_counts(),
        }

    def get_temperature(self, run_id: int) -> float | None:
        runner = self._runners.get(run_id)
        if runner is None or runner.ctx is None:
            return None
        return runner.ctx.temperature.value

    # ------------------------------------------------------------------
    # New methods
    # ------------------------------------------------------------------

    async def list_runs(
        self, session: AsyncSession, limit: int = 50, offset: int = 0
    ) -> tuple[list[RunInfo], int]:
        """Query runs table, returning (runs, total_count)."""
        count_result = await session.execute(select(func.count()).select_from(Run))
        total = count_result.scalar() or 0

        result = await session.execute(
            select(Run).order_by(Run.id.desc()).limit(limit).offset(offset)
        )
        rows = result.scalars().all()
        runs = [
            RunInfo(
                run_id=r.id,
                status=r.status,
                codelet_count=r.codelet_count,
                temperature=r.temperature,
                initial=r.initial_string,
                modified=r.modified_string,
                target=r.target_string,
                answer=r.answer_string,
                justify_mode=bool(r.justify_mode),
                # Explicit None check: 0 is a real, meaningful value here and `or`
                # would silently turn it into the default.
                spreading_threshold=(
                    100 if r.spreading_threshold is None else int(r.spreading_threshold)
                ),
            )
            for r in rows
        ]
        return runs, total

    async def _run_free(
        self,
        session: AsyncSession,
        run_id: int,
        runner: EngineRunner,
        workers: int,
        max_steps: int,
    ) -> RunInfo:
        """Drive a Run free-running, then persist it exactly as a serial Run.

        The engine work happens in worker *threads* and is handed to a thread executor so
        the event loop stays free — otherwise a run would block every other request for
        its whole duration, including the stop control.

        Persistence is unchanged: the sink has been collecting throughout, and it is
        flushed here once, as for a serial Run. That is the point of the ``RunSink`` port
        — the engine emits the same events in the same order whether one worker or eight
        produced them, so no mode needed teaching about concurrency.
        """
        import asyncio

        fast = self._is_fast(run_id)
        if not fast:
            await session.execute(
                update(Run).where(Run.id == run_id).values(status="running")
            )
            await session.commit()

        engine = FreeRunningEngine(runner, workers=workers)
        result = await asyncio.to_thread(engine.run, max_steps)
        self._free_run_telemetry[run_id] = result.summary()

        status_str = runner.status
        if not fast:
            await self._flush_sink(session, run_id)
            await session.execute(
                update(Run)
                .where(Run.id == run_id)
                .values(
                    codelet_count=runner.ctx.codelet_count,
                    temperature=runner.ctx.temperature.value,
                    status=status_str,
                    answer_string=runner.ctx.workspace.answer_string.text
                    if runner.ctx.workspace.answer_string
                    else None,
                )
            )
            await session.commit()
        self._stop_flags.pop(run_id, None)

        ws = runner.ctx.workspace
        return RunInfo(
            run_id=run_id,
            mode=self._modes.get(run_id, MODE_NORMAL),
            status=status_str,
            codelet_count=runner.ctx.codelet_count,
            temperature=runner.ctx.temperature.value,
            initial=ws.initial_string.text,
            modified=ws.modified_string.text,
            target=ws.target_string.text,
            answer=ws.answer_string.text if ws.answer_string else None,
            justify_mode=runner.ctx.justify_mode,
            spreading_threshold=runner.ctx.spreading_activation_threshold,
        )

    async def run_to_completion(
        self, session: AsyncSession, run_id: int, max_steps: int = 0
    ) -> RunInfo:
        """Step in a loop until answer found, max_steps reached, or stop flag set."""
        runner = self._runners.get(run_id)
        if runner is None:
            raise ValueError(f"Run {run_id} not found or not loaded")

        self._stop_flags[run_id] = False
        runner.status = STATUS_RUNNING

        workers = self._workers.get(run_id, 1)
        if workers > 1:
            return await self._run_free(session, run_id, runner, workers, max_steps)

        fast = self._is_fast(run_id)
        if not fast:
            # Update DB status to running
            await session.execute(
                update(Run).where(Run.id == run_id).values(status="running")
            )
            await session.commit()

        # How often to hand control back to the event loop.  The plan asks for the
        # per-codelet ``await asyncio.sleep(0)`` to go, and it should: it cost about
        # 16 µs per codelet, which at this engine's rate is a fifth of the budget for
        # a codelet.  Removing it outright is not an option, though, because the stop
        # flag and the breakpoint are set by *other* HTTP requests, and a loop that
        # never yields never lets them be served — the run would become uninterruptible.
        # Yielding once per update cycle keeps the pause and stop controls responsive
        # to within about a millisecond while removing fourteen fifteenths of the cost.
        ucl = self.meta.get_param("update_cycle_length", 15)
        step = 0

        while runner.status == STATUS_RUNNING:
            if max_steps > 0 and step >= max_steps:
                runner.status = STATUS_HALTED
                break

            if self._stop_flags.get(run_id, False):
                runner.status = STATUS_PAUSED
                break

            # Check breakpoint
            bp = self._breakpoints.get(run_id)
            if bp is not None and runner.ctx.codelet_count >= bp:
                runner.status = STATUS_PAUSED
                break

            step_result = runner.step_mcat()
            if step_result.answer_found:
                runner.status = STATUS_ANSWER_FOUND

            step += 1

            if runner.ctx.codelet_count % ucl == 0:
                await asyncio.sleep(0)

        # The Run has stopped, so the engine emits its closing event and the sink is
        # written once for the whole run.
        runner.finish()

        status_str = runner.status
        if fast:
            self._stop_flags.pop(run_id, None)
            return RunInfo(
                run_id=run_id,
                status=status_str,
                codelet_count=runner.ctx.codelet_count,
                temperature=runner.ctx.temperature.value,
                initial=runner.ctx.workspace.initial_string.text,
                modified=runner.ctx.workspace.modified_string.text,
                target=runner.ctx.workspace.target_string.text,
                answer=runner.ctx.workspace.answer_string.text
                if runner.ctx.workspace.answer_string
                else None,
                justify_mode=runner.ctx.justify_mode,
                spreading_threshold=runner.ctx.spreading_activation_threshold,
                mode=MODE_FAST,
            )

        await self._flush_sink(session, run_id)

        # Final update
        await session.execute(
            update(Run)
            .where(Run.id == run_id)
            .values(
                codelet_count=runner.ctx.codelet_count,
                temperature=runner.ctx.temperature.value,
                status=status_str,
                answer_string=runner.ctx.workspace.answer_string.text
                if runner.ctx.workspace.answer_string
                else None,
            )
        )
        await session.commit()
        self._stop_flags.pop(run_id, None)

        return RunInfo(
            run_id=run_id,
            mode=self._modes.get(run_id, MODE_NORMAL),
            status=status_str,
            codelet_count=runner.ctx.codelet_count,
            temperature=runner.ctx.temperature.value,
            initial=runner.ctx.workspace.initial_string.text,
            modified=runner.ctx.workspace.modified_string.text,
            target=runner.ctx.workspace.target_string.text,
            answer=runner.ctx.workspace.answer_string.text
            if runner.ctx.workspace.answer_string
            else None,
            justify_mode=runner.ctx.justify_mode,
            spreading_threshold=int(
                getattr(runner.ctx, "spreading_activation_threshold", 100)
            ),
        )

    def stop_run(self, run_id: int) -> None:
        """Set stop flag to interrupt a running run."""
        runner = self._runners.get(run_id)
        if runner is None:
            raise ValueError(f"Run {run_id} not found or not loaded")
        self._stop_flags[run_id] = True

    async def reset_run(self, session: AsyncSession, run_id: int) -> RunInfo:
        """Re-initialize the engine with the same parameters."""
        runner = self._runners.get(run_id)
        if runner is None:
            raise ValueError(f"Run {run_id} not found or not loaded")

        # Get original params from DB
        result = await session.execute(select(Run).where(Run.id == run_id))
        run = result.scalar_one_or_none()
        if run is None:
            raise ValueError(f"Run {run_id} not found in database")

        # Reset means "this same problem and seed again", so the run's settings
        # should survive it. `init_mcat` re-reads the spreading threshold from the
        # metadata default, which silently discarded whatever the user had chosen.
        threshold = getattr(runner.ctx, "spreading_activation_threshold", None)

        # Re-init engine
        runner.init_mcat(
            run.initial_string,
            run.modified_string,
            run.target_string,
            answer=run.answer_string,
            seed=run.seed,
            memory=_global_memory,
        )
        if threshold is not None:
            runner.ctx.spreading_activation_threshold = threshold

        # Delete old snapshots and trace events
        await session.execute(
            delete(CycleSnapshot).where(CycleSnapshot.run_id == run_id)
        )
        # The tables Phase 0 added. Without these a deleted run left its boundary
        # captures and its audit log behind — rows keyed to a run id that no longer
        # exists, which nothing would ever read and nothing would ever clean up.
        await session.execute(
            delete(RunStateCapture).where(RunStateCapture.run_id == run_id)
        )
        await session.execute(
            delete(AuditAction).where(AuditAction.run_id == run_id)
        )
        await session.execute(
            delete(TraceEventRow).where(TraceEventRow.run_id == run_id)
        )

        # Reset DB row
        await session.execute(
            update(Run)
            .where(Run.id == run_id)
            .values(
                status="initialized",
                codelet_count=0,
                temperature=runner.ctx.temperature.value,
            )
        )

        await session.commit()

        # A reset run gets a fresh sink of its own mode: the old one may hold records
        # buffered from before the reset, and those describe a run that no longer
        # exists.  The mode is a property of the Run and survives a reset.
        self._sinks[run_id] = sink_for_mode(self._modes.get(run_id, MODE_NORMAL))
        runner.ctx.sink = self._sinks[run_id]

        # Clear control state
        self._breakpoints.pop(run_id, None)
        self._step_sizes.pop(run_id, None)
        self._stop_flags.pop(run_id, None)

        return RunInfo(
            run_id=run_id,
            status="initialized",
            codelet_count=0,
            temperature=runner.ctx.temperature.value,
            initial=run.initial_string,
            modified=run.modified_string,
            target=run.target_string,
            answer=run.answer_string,
            justify_mode=bool(run.justify_mode),
            spreading_threshold=(
                100 if run.spreading_threshold is None else int(run.spreading_threshold)
            ),
        )

    async def delete_run(self, session: AsyncSession, run_id: int) -> None:
        """Delete a run and all associated state from DB and memory."""
        # Remove from in-memory runners
        self._runners.pop(run_id, None)
        self._breakpoints.pop(run_id, None)
        self._step_sizes.pop(run_id, None)
        self._stop_flags.pop(run_id, None)

        # Delete associated rows
        await session.execute(
            delete(CycleSnapshot).where(CycleSnapshot.run_id == run_id)
        )
        # The tables Phase 0 added. Without these a deleted run left its boundary
        # captures and its audit log behind — rows keyed to a run id that no longer
        # exists, which nothing would ever read and nothing would ever clean up.
        await session.execute(
            delete(RunStateCapture).where(RunStateCapture.run_id == run_id)
        )
        await session.execute(
            delete(AuditAction).where(AuditAction.run_id == run_id)
        )
        await session.execute(
            delete(TraceEventRow).where(TraceEventRow.run_id == run_id)
        )
        await session.execute(delete(Run).where(Run.id == run_id))
        await session.commit()

    async def delete_all_runs(self, session: AsyncSession) -> int:
        """Delete ALL runs, snapshots, trace events, and clear episodic memory."""
        # Clear in-memory state
        self._runners.clear()
        self._breakpoints.clear()
        self._step_sizes.clear()
        self._stop_flags.clear()

        # Delete all DB rows
        await session.execute(delete(CycleSnapshot))
        await session.execute(delete(RunStateCapture))
        await session.execute(delete(AuditAction))
        # Sessions group runs; with every run gone there is nothing left to group.
        await session.execute(delete(TrainingSession))
        await session.execute(delete(TraceEventRow))
        await session.execute(delete(AnswerDescriptionRow))
        await session.execute(delete(SnagDescriptionRow))

        count_result = await session.execute(select(func.count()).select_from(Run))
        count = count_result.scalar() or 0

        await session.execute(delete(Run))
        await session.commit()

        # Clear in-memory episodic memory
        _global_memory.clear()

        return count

    # ------------------------------------------------------------------
    # Trace & memory persistence helpers
    # ------------------------------------------------------------------

    async def _flush_sink(self, session: AsyncSession, run_id: int) -> None:
        """Write whatever the run's sink has buffered.

        Replaces ``_persist_new_trace_events`` and ``_persist_answer``, which the step
        loop used to call inline once per codelet.  The engine no longer knows that
        persistence exists: it emits events, the sink accumulates, and this is the one
        place a record reaches the session.

        A missing sink is not an error.  A run reloaded into a fresh process has a
        runner but no sink until one is attached, and a Fast Run's sink buffers
        nothing, so both correctly write nothing here.
        """
        sink = self._sinks.get(run_id)
        if sink is None:
            return
        await sink.flush(session, run_id)

    # ------------------------------------------------------------------
    # DB-backed trace & memory reads
    # ------------------------------------------------------------------

    async def get_trace_events_from_db(
        self,
        session: AsyncSession,
        run_id: int,
        event_type: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict]:
        """Read trace events from the database."""
        query = select(TraceEventRow).where(TraceEventRow.run_id == run_id)
        if event_type is not None:
            query = query.where(TraceEventRow.event_type == event_type)
        query = query.order_by(TraceEventRow.event_number).offset(offset).limit(limit)
        result = await session.execute(query)
        return [
            {
                "event_number": r.event_number,
                "event_type": r.event_type,
                "codelet_count": r.codelet_count,
                "temperature": r.temperature,
                "description": r.description or "",
                "theme_pattern": r.theme_pattern,
            }
            for r in result.scalars().all()
        ]

    async def clear_memory(self, session: AsyncSession) -> dict[str, int]:
        """Clear episodic memory in both of the places it lives.

        Answer and snag descriptions exist twice over: as rows in the database,
        and in the process-wide ``_global_memory`` that live runs read and write.
        ``get_memory_state_from_db`` serves the *rows*, so clearing only the
        in-process object left every answer still on screen — which looked like
        the clear had simply not worked.
        """
        answers = (
            await session.execute(select(func.count()).select_from(AnswerDescriptionRow))
        ).scalar() or 0
        snags = (
            await session.execute(select(func.count()).select_from(SnagDescriptionRow))
        ).scalar() or 0

        await session.execute(delete(AnswerDescriptionRow))
        await session.execute(delete(SnagDescriptionRow))

        # Clearing the memory *is* the end of the Training Session — it discards the one
        # thing that crosses Run boundaries, so the Runs before and after it did not
        # share anything and do not belong together.  WP3.0 says as much and the review
        # UI tells the user so, but nothing was closing the row: every Run in the
        # database therefore belonged to one session that had been open since the first
        # one, which makes the grouping useless precisely when it would start to matter.
        now = _utcnow()
        closed = (
            await session.execute(
                update(TrainingSession)
                .where(TrainingSession.ended_at.is_(None))
                .values(ended_at=now)
            )
        ).rowcount or 0
        await session.commit()

        # Cleared in place, so the runners holding this reference see it too.
        _global_memory.clear()

        return {"answers": answers, "snags": snags, "sessions_closed": closed}

    async def get_memory_state_from_db(self, session: AsyncSession) -> dict:
        """Read episodic memory from the database."""
        answers_result = await session.execute(
            select(AnswerDescriptionRow).order_by(AnswerDescriptionRow.id)
        )
        snags_result = await session.execute(
            select(SnagDescriptionRow).order_by(SnagDescriptionRow.id)
        )
        return {
            "answers": [
                {
                    "answer_id": a.id,
                    "run_id": a.run_id,
                    "problem": a.problem,
                    "top_rule_description": a.top_rule_description or "",
                    "bottom_rule_description": a.bottom_rule_description or "",
                    "top_rule_quality": a.top_rule_quality,
                    "bottom_rule_quality": a.bottom_rule_quality,
                    "quality": a.quality,
                    "temperature": a.temperature,
                    "themes": a.themes,
                    "unjustified_slippages": a.unjustified_slippages,
                    **_live_answer_fields(a.problem, a.top_rule_description),
                }
                for a in answers_result.scalars().all()
            ],
            "snags": [
                {
                    "snag_id": s.id,
                    "run_id": s.run_id,
                    "problem": s.problem,
                    "codelet_count": s.codelet_count,
                    "temperature": s.temperature,
                    "theme_pattern": s.theme_pattern,
                    "description": s.description or "",
                }
                for s in snags_result.scalars().all()
            ],
        }

    async def rehydrate_memory(self, session: AsyncSession) -> None:
        """Load episodic memory from DB into the in-memory singleton."""
        answers_result = await session.execute(
            select(AnswerDescriptionRow).order_by(AnswerDescriptionRow.id)
        )
        for a in answers_result.scalars().all():
            desc = AnswerDescription(
                problem=tuple(a.problem),
                top_rule_description=a.top_rule_description or "",
                bottom_rule_description=a.bottom_rule_description or "",
                top_rule_quality=a.top_rule_quality or 0.0,
                bottom_rule_quality=a.bottom_rule_quality or 0.0,
                quality=a.quality or 0.0,
                temperature=a.temperature or 0.0,
                themes=a.themes or {},
                unjustified_slippages=a.unjustified_slippages or [],
                run_id=a.run_id,
            )
            # Stored rather than appended, so the rehydrated answers take
            # ``answer_id`` from the memory's own counter.  ``/api/memory/compare``
            # looks answers up by that id.
            _global_memory.store_answer(desc)

        snags_result = await session.execute(
            select(SnagDescriptionRow).order_by(SnagDescriptionRow.id)
        )
        for s in snags_result.scalars().all():
            desc = SnagDescription(
                problem=tuple(s.problem),
                codelet_count=s.codelet_count or 0,
                temperature=s.temperature or 0.0,
                theme_pattern=s.theme_pattern or {},
                description=s.description or "",
                run_id=s.run_id,
            )
            _global_memory.store_snag(desc)

    def get_themespace_state(self, run_id: int) -> dict | None:
        """Serialize the current themespace state for the given run."""
        runner = self._runners.get(run_id)
        if runner is None or runner.ctx is None:
            return None
        return serialize_themespace_state(runner.ctx)

    def get_trace_events(
        self,
        run_id: int,
        event_type: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict] | None:
        """Return trace events from the in-memory trace, with optional filtering."""
        runner = self._runners.get(run_id)
        if runner is None or runner.ctx is None:
            return None

        events = runner.ctx.trace.events

        # Filter by event_type if specified
        if event_type is not None:
            events = [e for e in events if e.event_type == event_type]

        # Apply offset and limit
        events = events[offset : offset + limit]

        return [
            {
                "event_number": e.event_number,
                "event_type": e.event_type,
                "codelet_count": e.codelet_count,
                "temperature": e.temperature,
                "description": e.description,
                "theme_pattern": e.theme_pattern,
            }
            for e in events
        ]

    def get_memory_state(self) -> dict:
        """Return episodic memory contents (cross-run)."""
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
                }
                for a in _global_memory.answers
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
                for s in _global_memory.snags
            ],
        }

    def get_commentary(self, run_id: int, eliza_mode: bool = False) -> dict | None:
        """Return accumulated commentary text for the given run.

        Reads from the CommentaryLog on the EngineContext and renders
        all paragraphs in the requested voice mode.  Toggling eliza_mode
        re-renders the same paragraphs in the alternate voice — no
        regeneration needed, matching original Scheme behavior.
        """
        runner = self._runners.get(run_id)
        if runner is None or runner.ctx is None:
            return None

        return {
            "run_id": run_id,
            "commentary": runner.ctx.commentary.render(eliza_mode),
            "eliza_mode": eliza_mode,
            "paragraph_count": runner.ctx.commentary.count,
        }

    # ------------------------------------------------------------------
    # Breakpoint & execution control
    # ------------------------------------------------------------------

    def set_breakpoint(self, run_id: int, codelet_count: int) -> dict:
        """Set a breakpoint at a given codelet count."""
        if run_id not in self._runners:
            raise ValueError(f"Run {run_id} not found or not loaded")
        self._breakpoints[run_id] = codelet_count
        return {"run_id": run_id, "breakpoint": codelet_count}

    def clear_breakpoint(self, run_id: int) -> dict:
        """Clear the breakpoint for a run."""
        if run_id not in self._runners:
            raise ValueError(f"Run {run_id} not found or not loaded")
        self._breakpoints.pop(run_id, None)
        return {"run_id": run_id, "breakpoint": None}

    def set_step_size(self, run_id: int, step_size: int) -> dict:
        """Set the step size for the given run."""
        if run_id not in self._runners:
            raise ValueError(f"Run {run_id} not found or not loaded")
        self._step_sizes[run_id] = step_size
        return {"run_id": run_id, "step_size": step_size}

    # ------------------------------------------------------------------
    # Temperature clamping
    # ------------------------------------------------------------------

    def clamp_temperature(self, run_id: int, value: float, cycles: int = 0) -> dict:
        """Clamp the temperature for the given run."""
        runner = self._runners.get(run_id)
        if runner is None or runner.ctx is None:
            raise ValueError(f"Run {run_id} not found or not loaded")
        runner.ctx.temperature.clamp(value, cycles)
        return {
            "run_id": run_id,
            "temperature": runner.ctx.temperature.value,
            "clamped": True,
            "clamp_value": value,
            "clamp_cycles": cycles,
        }

    def unclamp_temperature(self, run_id: int) -> dict:
        """Unclamp the temperature for the given run."""
        runner = self._runners.get(run_id)
        if runner is None or runner.ctx is None:
            raise ValueError(f"Run {run_id} not found or not loaded")
        runner.ctx.temperature.unclamp()
        return {
            "run_id": run_id,
            "temperature": runner.ctx.temperature.value,
            "clamped": False,
        }

    # ------------------------------------------------------------------
    # Slipnet node clamping
    # ------------------------------------------------------------------

    def clamp_node(self, run_id: int, node_name: str, cycles: int = 0) -> dict:
        """Clamp a slipnet node for the given run."""
        runner = self._runners.get(run_id)
        if runner is None or runner.ctx is None:
            raise ValueError(f"Run {run_id} not found or not loaded")
        node = runner.ctx.slipnet.nodes.get(node_name)
        if node is None:
            raise ValueError(f"Slipnet node '{node_name}' not found")
        node.clamp(cycles)
        return {
            "run_id": run_id,
            "node_name": node_name,
            "clamped": True,
            "activation": node.activation,
            "clamp_cycles": cycles,
        }

    def unclamp_node(self, run_id: int, node_name: str) -> dict:
        """Unclamp a slipnet node for the given run."""
        runner = self._runners.get(run_id)
        if runner is None or runner.ctx is None:
            raise ValueError(f"Run {run_id} not found or not loaded")
        node = runner.ctx.slipnet.nodes.get(node_name)
        if node is None:
            raise ValueError(f"Slipnet node '{node_name}' not found")
        node.unclamp()
        return {
            "run_id": run_id,
            "node_name": node_name,
            "clamped": False,
            "activation": node.activation,
        }

    # ------------------------------------------------------------------
    # Theme clamping
    # ------------------------------------------------------------------

    def clamp_themes(self, run_id: int, themes: list[dict]) -> dict:
        """Clamp themes in the themespace for the given run.

        Each theme dict: {type, dimension, relation, activation}.
        """
        runner = self._runners.get(run_id)
        if runner is None or runner.ctx is None:
            raise ValueError(f"Run {run_id} not found or not loaded")

        clamped = []
        for t in themes:
            for cluster in runner.ctx.themespace.clusters:
                if (
                    cluster.theme_type == t.get("type", "")
                    and cluster.dimension == t.get("dimension", "")
                ):
                    theme = cluster.get_theme(t.get("relation"))
                    if theme is not None:
                        activation = t.get("activation", 100.0)
                        theme.clamp(activation)
                        clamped.append({
                            "type": cluster.theme_type,
                            "dimension": cluster.dimension,
                            "relation": theme.relation,
                            "activation": theme.activation,
                        })
        return {"run_id": run_id, "clamped_themes": clamped}

    def unclamp_themes(self, run_id: int) -> dict:
        """Unclamp all themes in the themespace for the given run."""
        runner = self._runners.get(run_id)
        if runner is None or runner.ctx is None:
            raise ValueError(f"Run {run_id} not found or not loaded")

        for cluster in runner.ctx.themespace.clusters:
            for theme in cluster.themes:
                theme.unclamp()
        return {"run_id": run_id, "unclamped": True}

    # ------------------------------------------------------------------
    # Codelet clamping
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Spreading activation threshold
    # ------------------------------------------------------------------

    async def set_spreading_threshold(
        self, session: AsyncSession, run_id: int, threshold: int,
    ) -> dict:
        """Set the spreading activation threshold for the given run.

        0 = all active nodes spread (permissive).
        100 = only fully-active nodes spread (original Scheme behaviour).

        Written to the run row as well as the live engine: the threshold changes
        what the run does, so it is part of the record of that run rather than a
        transient setting that disappears on restart.
        """
        runner = self._runners.get(run_id)
        if runner is None or runner.ctx is None:
            raise ValueError(f"Run {run_id} not found or not loaded")
        threshold = max(0, min(100, threshold))
        runner.ctx.spreading_activation_threshold = threshold
        await session.execute(
            update(Run).where(Run.id == run_id).values(spreading_threshold=threshold)
        )
        await session.commit()
        return {
            "run_id": run_id,
            "spreading_activation_threshold": threshold,
        }

    def get_spreading_threshold(self, run_id: int) -> dict:
        """Get the current spreading activation threshold for the given run."""
        runner = self._runners.get(run_id)
        if runner is None or runner.ctx is None:
            raise ValueError(f"Run {run_id} not found or not loaded")
        return {
            "run_id": run_id,
            "spreading_activation_threshold": runner.ctx.spreading_activation_threshold,
        }

    # ------------------------------------------------------------------
    # Codelet clamping
    # ------------------------------------------------------------------

    def clamp_codelets(self, run_id: int, codelet_type: str, urgency: int) -> dict:
        """Clamp a codelet type to a minimum urgency for the given run."""
        runner = self._runners.get(run_id)
        if runner is None or runner.ctx is None:
            raise ValueError(f"Run {run_id} not found or not loaded")
        runner.ctx.coderack.clamp_codelet_type(codelet_type, urgency)
        return {
            "run_id": run_id,
            "codelet_type": codelet_type,
            "urgency": urgency,
            "clamped": True,
        }

    def unclamp_codelets(self, run_id: int, codelet_type: str) -> dict:
        """Unclamp a codelet type for the given run."""
        runner = self._runners.get(run_id)
        if runner is None or runner.ctx is None:
            raise ValueError(f"Run {run_id} not found or not loaded")
        runner.ctx.coderack.unclamp_codelet_type(codelet_type)
        return {
            "run_id": run_id,
            "codelet_type": codelet_type,
            "clamped": False,
        }
