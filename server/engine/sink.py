"""The ``RunSink`` port — where a run's record goes, if anywhere.

Petacat has three persistence modes.  Fast Run writes nothing, ever; Normal captures
the complete state at the two Run boundaries; Audit records every state-changing
action.  The point of this module is that **the engine does not know which of those is
in force**.  It emits the same events in the same order in every mode, and the mode is
purely a question of which implementation is attached.

That constraint is worth stating as a rule, because the obvious alternative fails
quietly: if the engine ever asks ``if mode == "fast"``, the modes stop being
interchangeable and the mode-equivalence test — that a Fast run and a Normal run of
the same problem think identically — stops meaning anything, since the code paths it
compares are no longer the same path.  There is therefore no mode flag anywhere under
``server/engine/``.

Three design decisions worth the words
--------------------------------------

**Events carry the live context, never a payload.** Every method takes the
``EngineContext`` itself.  Serialisation is the sink's business and happens inside the
sink, so a mode that stores nothing builds nothing: no dict, no JSON, no record object
that exists only because something *might* persist it.  Handing the sink a pre-built
payload would defeat Fast Run before it started, because the payload would be
constructed whether or not anyone wanted it.

**The methods are synchronous.** The engine contains no awaits and, after WP3.3, its
step loop contains none either — the per-codelet coroutine and ``asyncio.sleep(0)``
that used to sit in it cost about 16 µs per codelet for no benefit.  The database is
async, so the sinks that use one buffer in memory and flush at a Run boundary, where
the service layer is in async context anyway.  That is not a workaround: Normal only
writes at the two boundaries by definition, and Audit is explicitly allowed to
accumulate and flush once at Run end.  Its requirement is completeness, not
contemporaneity.

**The protocol lives in the engine; the implementations do not.** ``server/engine/``
imports no database layer, and a test enforces it.  Fast, Normal and Audit sinks all
live under ``server/services/``.  What the engine holds is the shape of the port and
``NullSink`` — see below.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from server.engine.coderack import Codelet
    from server.engine.runner import EngineContext, StepResult
    from server.engine.trace import TraceEvent

#: How a structure's presence in the Workspace changed.  Audit reconstructs
#: intermediate states from these, so the pair has to be exhaustive: every structure
#: that enters or leaves the Workspace does so through one of them.
STRUCTURE_BUILT = "built"
STRUCTURE_BROKEN = "broken"

#: The valence signal (Phase 2).  Delivered by the harness on a channel of its own
#: rather than perceived as a percept in the Workspace, so it arrives as an event here
#: rather than as anything the codelets can see.
VALENCE_LOVE = "love"
VALENCE_NOT_LOVE = "not-love"


@runtime_checkable
class RunSink(Protocol):
    """Everything the engine will tell you about a run.

    A ``Protocol`` rather than a base class, so an implementation is anything with the
    right methods and the service layer need not import the engine to be one.
    ``runtime_checkable`` makes ``isinstance`` usable in tests; note it checks only
    that the methods exist, which is all that is wanted here.

    Implementations must not raise.  A sink is a recorder, and a recorder that can
    fail a run has changed what the run does — which would break the one rule the
    modes exist to keep.
    """

    def on_run_created(self, ctx: EngineContext) -> None:
        """The Run is initialised and about to execute its first codelet.

        Normal mode's first complete-state capture. Everything a Run inherits from its
        Training Session — the Episodic Memory, and nothing else in Phase 0 — is
        already in place, which is what makes the captured state sufficient to
        re-execute the Run from.
        """

    def on_codelet(self, ctx: EngineContext, codelet: Codelet, result: StepResult) -> None:
        """One codelet has finished executing.

        The highest-frequency event by a wide margin — a couple of thousand per run —
        so an implementation that does per-codelet work is choosing to be slow. Fast
        Run's implementation must be an empty body, not a cheap one.
        """

    def on_trace_event(self, ctx: EngineContext, event: TraceEvent) -> None:
        """An event was recorded in the Temporal Trace.

        Distinct from ``on_codelet`` because the Trace is the *cognitive* level: a run
        of two thousand codelets produces a couple of dozen trace events, being only
        those that cleared their importance threshold.
        """

    def on_structure_change(
        self, ctx: EngineContext, structure: Any, change: str
    ) -> None:
        """A structure was built into, or broken out of, the Workspace.

        ``change`` is ``STRUCTURE_BUILT`` or ``STRUCTURE_BROKEN``. Together with the
        Run-start state these are what let Audit reconstruct every intermediate state
        in forward order.
        """

    def on_answer(self, ctx: EngineContext, answer: str, quality: float) -> None:
        """A codelet reported an answer."""

    def on_valence(self, ctx: EngineContext, signal: str, strength: float) -> None:
        """An external valence signal arrived (Phase 2).

        Nothing in Phase 0 emits this. It is declared now because the port is the
        thing later phases attach to, and adding an event to a protocol that already
        has three implementations is more disruptive than reserving it.
        """

    def on_turn_end(self, ctx: EngineContext) -> None:
        """The Run has stopped — answered, halted, or given up.

        Normal mode's second complete-state capture, and where a buffering Audit sink
        flushes.

        Named for the *turn* rather than the Run because Phase 2 makes Petacat a
        participant in a dialogue, and a turn is the unit it produces. In Phase 0 a Run
        produces exactly one turn, so the two boundaries coincide. If that ever stops
        being true, Normal's end-of-Run capture needs an event of its own rather than
        borrowing this one.
        """


class NullSink:
    """A sink that does nothing, which is what lets the engine emit unconditionally.

    Its presence in the engine is not a mode implementation — it holds no persistence
    knowledge and could not acquire any, since the engine cannot import the database
    layer. It exists so that ``ctx.sink`` is never ``None`` and no call site needs a
    guard. The alternative, a null check before each of seven events on a path that
    runs thousands of times per second, adds branches to the hot loop in order to
    express something the type system can express for free.

    Fast Run's sink is this, or a subclass of it that also refuses to be given a
    database. What Fast Run must never be is a sink that collects records for a writer
    that is never called: that would satisfy "writes nothing" while still paying to
    build everything.
    """

    __slots__ = ()

    def on_run_created(self, ctx: EngineContext) -> None: ...
    def on_codelet(self, ctx: EngineContext, codelet: Codelet, result: StepResult) -> None: ...
    def on_trace_event(self, ctx: EngineContext, event: TraceEvent) -> None: ...
    def on_structure_change(self, ctx: EngineContext, structure: Any, change: str) -> None: ...
    def on_answer(self, ctx: EngineContext, answer: str, quality: float) -> None: ...
    def on_valence(self, ctx: EngineContext, signal: str, strength: float) -> None: ...
    def on_turn_end(self, ctx: EngineContext) -> None: ...

    def __repr__(self) -> str:
        return "NullSink()"
