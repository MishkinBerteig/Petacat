"""``RunSink`` implementations — where each persistence mode puts a run's record.

The engine emits the same events in the same order whatever is attached here
(``server/engine/sink.py``); this module is the entire difference between the modes.

Why buffering, and why that is not a compromise
-----------------------------------------------
The engine's loop is synchronous and the database is not, so a sink cannot write as it
is called.  Every sink here therefore accumulates in memory and exposes ``async def
flush(session, run_id)``, which the service layer calls at a point where it is in async
context anyway.

That is what the modes actually want rather than a limitation worked around.  Audit's
requirement is explicitly completeness and not contemporaneity — it may buffer during
the Run and flush once at the end.  Normal writes only at the two Run boundaries by
definition.  And the arrangement removes the per-codelet ``await`` that used to sit in
the step loop, which cost around 16 µs per codelet to schedule a coroutine that almost
always found nothing to do: the trace slice it examined was empty about 99.2% of the
time.

Fast Run buffers nothing at all, which is the one case where buffering would be the
wrong answer.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from server.engine.runner import EngineContext, StepResult
from server.engine.sink import STRUCTURE_BUILT, NullSink
from server.engine.serialization import describe_structure
from server.engine.state_graph import capture_run_state
from server.engine.trace import SNAG, TraceEvent
from server.models.run import (
    AnswerDescriptionRow,
    AuditAction,
    RunStateCapture,
    SnagDescriptionRow,
    TraceEventRow,
)

#: Persistence mode names.  Mode is a property of a Run, chosen at creation.
MODE_FAST = "fast"
MODE_NORMAL = "normal"
MODE_AUDIT = "audit"


class FastSink(NullSink):
    """Writes nothing, ever, and builds nothing that could be written.

    A subclass of the engine's ``NullSink`` rather than a fresh no-op class, so that
    "Fast Run does nothing" is expressed once.  It inherits empty ``__slots__``, which
    is doing real work here: the requirement Fast Run is judged against is not only
    that no row reaches the database but that **no storable representation is
    constructed at all** — no JSON built to be discarded, no list of records
    accumulated for a writer that is never called.  With no instance dictionary there
    is nowhere for such a buffer to appear without the change being visible in review.
    """

    __slots__ = ()

    async def flush(self, session: AsyncSession, run_id: int) -> None:
        """Deliberately not a no-op that touches the session.

        It does not take a session lazily, open one, or stage anything: a Fast Run must
        complete with the database *stopped*, so any code path here that assumed a live
        session would turn an unavailable database into a failed run.
        """

    def __repr__(self) -> str:
        return "FastSink()"


class TraceRecordingSink:
    """Buffers the trace-level record of a run and writes it in one go.

    This is the behaviour the step loop used to perform inline, moved behind the port
    and batched.  It is the common part of Normal and Audit — both keep the Temporal
    Trace, the answers and the snags — with each of those adding its own state capture
    on top.

    What it does *not* do is take a per-15-codelet snapshot.  Those are retired: they
    were 1–6 MB of JSONB per run that no code path could read back, and no caller of
    the four ``restore_*`` functions ever existed.
    """

    def __init__(self) -> None:
        self._trace_events: list[TraceEvent] = []
        self._answers: list[Any] = []
        #: The Episodic Memory's snag descriptions, as they are created.  Captured
        #: here rather than derived from SNAG trace events, because ``record_snag``
        #: deduplicates: a snag hit repeatedly produces an event each time but one
        #: description.  Writing a row per event made the database disagree with the
        #: memory about how many snags there were — ten rows against one description on
        #: an ordinary run, with the rows' descriptions empty.
        self._snags: list[Any] = []

    # -- engine-facing events ------------------------------------------

    def on_run_created(self, ctx: EngineContext) -> None: ...

    def on_codelet(
        self, ctx: EngineContext, codelet: Any, result: StepResult
    ) -> None: ...

    def on_trace_event(self, ctx: EngineContext, event: TraceEvent) -> None:
        self._trace_events.append(event)
        if event.event_type == SNAG:
            # Take whatever snag descriptions the memory has gained.  It gains none for
            # a snag it already knows (``snag_present?``, ``answers.ss:1162``), which is
            # exactly the deduplication the rows should inherit.
            known = len(self._snags)
            if len(ctx.memory.snags) > known:
                self._snags.extend(ctx.memory.snags[known:])

    def on_structure_change(
        self, ctx: EngineContext, structure: Any, change: str
    ) -> None: ...

    def on_answer(self, ctx: EngineContext, answer: str, quality: float) -> None:
        # The engine has already stored the description in Episodic Memory by the time
        # this fires; the last one is the answer just found.
        if ctx.memory.answers:
            self._answers.append(ctx.memory.answers[-1])

    def on_valence(self, ctx: EngineContext, signal: str, strength: float) -> None: ...

    def on_turn_end(self, ctx: EngineContext) -> None: ...

    # -- service-facing ------------------------------------------------

    @property
    def pending(self) -> int:
        """How many records are waiting. Used by tests to show Fast Run buffers none."""
        return len(self._trace_events) + len(self._answers) + len(self._snags)

    async def flush(self, session: AsyncSession, run_id: int) -> None:
        """Stage everything buffered so far and forget it.

        Staging rather than committing: the caller owns the transaction, and one commit
        per API call is what keeps a run from paying for a round-trip per event.
        Clearing the buffers makes repeated flushes safe, which matters because the
        service layer flushes per API call *and* at the end of a Run.
        """
        for event in self._trace_events:
            session.add(
                TraceEventRow(
                    run_id=run_id,
                    event_number=event.event_number,
                    event_type=event.event_type,
                    codelet_count=event.codelet_count,
                    temperature=event.temperature,
                    description=event.description,
                    # §4.4 makes the structures part of what an event *is* — MetaCat's
                    # Trace display highlights them — so a recorded run has to keep
                    # them or its events cannot be inspected the way a live one's can.
                    # Descriptions rather than references: the objects do not outlive
                    # the process, and what the reviewer needs is which structure, not
                    # the structure itself.
                    structures=[
                        describe_structure(s) for s in (event.structures or [])
                    ],
                    theme_pattern=event.theme_pattern,
                )
            )

        for snag in self._snags:
            snag.run_id = run_id
            session.add(
                SnagDescriptionRow(
                    snag_id=snag.snag_id,
                    run_id=run_id,
                    problem=list(snag.problem),
                    codelet_count=snag.codelet_count,
                    temperature=snag.temperature,
                    theme_pattern=snag.theme_pattern,
                    description=snag.description,
                )
            )

        for answer in self._answers:
            answer.run_id = run_id
            row = AnswerDescriptionRow(
                answer_id=answer.answer_id,
                run_id=run_id,
                problem=list(answer.problem),
                top_rule_description=answer.top_rule_description,
                bottom_rule_description=answer.bottom_rule_description,
                top_rule_quality=answer.top_rule_quality,
                bottom_rule_quality=answer.bottom_rule_quality,
                quality=answer.quality,
                temperature=answer.temperature,
                themes=answer.themes,
                unjustified_slippages=answer.unjustified_slippages,
                top_themes=answer.top_themes,
                bottom_themes=answer.bottom_themes,
                unjustified_themes=answer.unjustified_themes,
                top_rule_abstractness=answer.top_rule_abstractness,
                bottom_rule_abstractness=answer.bottom_rule_abstractness,
                theme_abstractness=answer.theme_abstractness,
                activation=answer.activation,
                top_rule_signature=answer.top_rule_signature,
                bottom_rule_signature=answer.bottom_rule_signature,
            )
            session.add(row)

        self._trace_events.clear()
        self._answers.clear()
        self._snags.clear()

    def __repr__(self) -> str:
        return f"{type(self).__name__}(pending={self.pending})"


class NormalSink(TraceRecordingSink):
    """The complete Petacat state at the two Run boundaries, and nothing between.

    Fast and Normal differ in **exactly one thing**: Normal captures the complete state
    at Run start and Run end, and Fast captures nothing.  Not cadence, not detail level,
    not what the engine does.  Stating it that narrowly is what makes Normal cheap — two
    captures rather than the 148 snapshots it replaces — and what makes the
    mode-equivalence test meaningful, because there is nothing else that *could* differ.

    Why complete state rather than the problem and the seed: a Run inherits its Episodic
    Memory from whatever preceded it in the Training Session, so ``(problem, seed)`` does
    not determine its behaviour and ``(complete starting state, problem, seed)`` does.
    That is also what makes a Normal Run **reproducible by re-execution** — reload the
    recorded start state, run, and the recorded end state must follow — rather than by
    replay, which would need the mid-Run detail that is deliberately Audit's job.
    """

    def __init__(self) -> None:
        super().__init__()
        self._captures: list[tuple[str, int, dict]] = []

    def on_run_created(self, ctx: EngineContext) -> None:
        self._captures.append(("start", ctx.codelet_count, capture_run_state(ctx)))

    def on_turn_end(self, ctx: EngineContext) -> None:
        self._captures.append(("end", ctx.codelet_count, capture_run_state(ctx)))

    @property
    def pending(self) -> int:
        return super().pending + len(self._captures)

    async def flush(self, session: AsyncSession, run_id: int) -> None:
        await super().flush(session, run_id)
        for boundary, codelet_count, state in self._captures:
            session.add(
                RunStateCapture(
                    run_id=run_id,
                    boundary=boundary,
                    codelet_count=codelet_count,
                    state=state,
                )
            )
        self._captures.clear()


class AuditSink(TraceRecordingSink):
    """Every state-changing action during the Run, as a forward log.

    Audit's requirement is **completeness, not contemporaneity of writing**: it may
    accumulate in memory and flush once at Run end, and it does.  What it may not do is
    miss an action, because the guarantee is that any intermediate state can be
    reconstructed by replaying forward from the Run-start capture.

    It also forces serial execution.  A record of actions with no record of commit order
    would not reconstruct anything under free-running, and Audit is the phase's
    **serial reference mode** — the fully-recorded, one-codelet-at-a-time execution that
    every later phase validates against. That is why Audit stays serial forever rather
    than being a slow setting of a parallel engine.

    *Forward only in Phase 0.* Backwards scrubbing constrains the record format and not
    merely the UI, so ``before`` carries enough prior state for an action to be inverted
    later; the inverse-replay machinery is deliberately not built.
    """

    def __init__(self) -> None:
        super().__init__()
        self._actions: list[AuditAction] = []
        self._start_capture: dict | None = None
        self._end_capture: dict | None = None
        self._sequence = 0

    def _record(
        self, ctx: EngineContext, action_type: str, payload: dict, before: dict | None = None
    ) -> None:
        self._sequence += 1
        self._actions.append(
            AuditAction(
                sequence=self._sequence,
                codelet_count=ctx.codelet_count,
                action_type=action_type,
                temperature=ctx.temperature.value,
                payload=payload,
                before=before,
            )
        )

    def on_run_created(self, ctx: EngineContext) -> None:
        self._start_capture = capture_run_state(ctx)

    def on_codelet(
        self, ctx: EngineContext, codelet: Any, result: StepResult
    ) -> None:
        self._record(
            ctx,
            "codelet",
            {
                "codelet_type": codelet.codelet_type,
                "urgency": codelet.urgency,
                "time_stamp": codelet.time_stamp,
                # Argument *shapes* rather than the objects themselves. The objects are
                # in the workspace the replay is reconstructing, so storing them here
                # would duplicate the graph once per codelet.
                "arguments": {k: type(v).__name__ for k, v in codelet.arguments.items()},
            },
        )

    def on_trace_event(self, ctx: EngineContext, event: TraceEvent) -> None:
        super().on_trace_event(ctx, event)
        self._record(
            ctx,
            "trace_event",
            {
                "event_number": event.event_number,
                "event_type": event.event_type,
                "description": event.description,
            },
        )

    def on_structure_change(
        self, ctx: EngineContext, structure: Any, change: str
    ) -> None:
        self._record(
            ctx,
            f"structure_{change}",
            {
                "structure": type(structure).__name__,
                "id": getattr(structure, "id", None),
                "strength": round(getattr(structure, "strength", 0.0)),
                "proposal_level": getattr(structure, "proposal_level", None),
            },
            # The inverse of a build is a break and vice versa, but reinstating a broken
            # structure needs its level and strength from before the change. Recorded
            # now, unused in Phase 0.
            before={
                "proposal_level": (
                    "evaluated" if change == STRUCTURE_BUILT else "built"
                ),
            },
        )

    def on_answer(self, ctx: EngineContext, answer: str, quality: float) -> None:
        super().on_answer(ctx, answer, quality)
        self._record(ctx, "answer", {"answer": answer, "quality": quality})

    def on_valence(self, ctx: EngineContext, signal: str, strength: float) -> None:
        self._record(ctx, "valence", {"signal": signal, "strength": strength})

    def on_turn_end(self, ctx: EngineContext) -> None:
        self._end_capture = capture_run_state(ctx)

    @property
    def pending(self) -> int:
        return super().pending + len(self._actions)

    async def flush(self, session: AsyncSession, run_id: int) -> None:
        await super().flush(session, run_id)
        for boundary, state in (("start", self._start_capture), ("end", self._end_capture)):
            if state is None:
                continue
            session.add(
                RunStateCapture(
                    run_id=run_id,
                    boundary=boundary,
                    codelet_count=state["runner"]["codelet_count"],
                    state=state,
                )
            )
        self._start_capture = None
        self._end_capture = None

        for action in self._actions:
            action.run_id = run_id
            session.add(action)
        self._actions.clear()


#: Mode name to sink. The engine never consults this; only run creation does.
SINKS_BY_MODE = {
    MODE_FAST: FastSink,
    MODE_NORMAL: NormalSink,
    MODE_AUDIT: AuditSink,
}


def sink_for_mode(mode: str):
    """Build the sink a mode calls for, rejecting an unknown mode loudly.

    Falling back to a default would be the wrong kindness: a typo in a mode name would
    silently give a Fast Run when Audit was asked for, and the missing record would only
    be noticed when someone tried to review it.
    """
    try:
        return SINKS_BY_MODE[mode]()
    except KeyError:
        raise ValueError(
            f"unknown persistence mode {mode!r}; expected one of "
            f"{sorted(SINKS_BY_MODE)}"
        ) from None
