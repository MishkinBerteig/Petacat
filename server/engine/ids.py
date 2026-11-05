"""Per-run identifier allocation.

Metacat's codelets, workspace objects, workspace structures and trace events each
carry a small integer identifier.  Until this module existed those identifiers came
from class-level counters incremented in place — ``Codelet._next_id += 1`` and four
more like it — which made an identifier a function of everything the *process* had
run rather than of the run that produced it.  The same ``(problem, seed)`` executed
three times in one process produced identical cognition but ``event_number``
sequences starting at 1, 19 and 41.

That is not merely untidy.  ``TraceEvent.event_number`` is persisted to
``trace_events.event_number`` and is the ordering key of
``get_trace_events_from_db``, so process history leaked into the stored record of a
run.  And the read-modify-write is not atomic: under free-threaded CPython two
threads can read the same value and both claim it, so the counters are also a data
race waiting for Workstream B to arrive.  Both problems have the same fix, and doing
it now — while it is a mechanical change to five constructors — is much cheaper than
doing it once codelets run concurrently.

Scoping
-------
An allocator belongs to whatever the identifiers are meaningful within:

- The **run** owns codelet, object, structure and trace-event numbering.
  ``EngineContext.ids`` holds that allocator, and the engine binds it as the current
  allocator for the duration of every engine entry point.
- The **Episodic Memory** owns answer and snag numbering, because Episodic Memory is
  the one component that deliberately outlives a run: across episodic runs it
  accumulates answers across many runs, and ``POST /api/memory/compare`` looks answers
  up by ``answer_id``.  Per-run numbering there would hand two different answers in
  one memory the same identifier.  ``EpisodicMemory`` therefore carries its own
  allocator and stamps descriptions as they are stored.

Binding
-------
The current allocator is held in a :class:`~contextvars.ContextVar` rather than a
module global, and is re-bound at each engine entry point from the runner's own
context.  Both choices matter:

- A ``ContextVar`` is per-thread, so two runners stepping concurrently in different
  threads cannot take numbers from each other's allocator.
- Re-binding per entry point, rather than once per run, is what makes this correct
  under the service layer's model of one API request per step.  Each request runs in
  a fresh asyncio task with a fresh context, so an allocator bound during run
  creation would simply not be visible when the next request stepped the run.

When nothing is bound, allocation raises ``NoRunBound``.  There is no process-wide
default: it was shared run state (two runs, or a run and a test, drew from one counter),
and the only code that ever reached it was code running outside a run.  Episodic Memory
numbers its own answers and snags with the allocator it carries, and needs no binding.
"""

from __future__ import annotations

import threading
from contextlib import contextmanager
from contextvars import ContextVar, Token
from typing import Iterator

#: Identifier kinds.  Each is numbered independently, so a run's third codelet and
#: its third bond are both 3 — matching the per-class counters this replaces.
KIND_CODELET = "codelet"
KIND_OBJECT = "object"
KIND_STRUCTURE = "structure"
KIND_TRACE_EVENT = "trace_event"
KIND_ANSWER = "answer"
KIND_SNAG = "snag"


class IdAllocator:
    """Monotonic per-kind counters, safe to share between threads.

    The lock is held only around an integer increment.  An uncontended acquire costs
    tens of nanoseconds against the roughly ten thousand allocations a run makes, so
    the cost is well under a millisecond of a run measured in hundreds — cheap enough
    that there is no reason to trade correctness for it.
    """

    __slots__ = ("_lock", "_counters")

    def __init__(self, counters: dict[str, int] | None = None) -> None:
        self._lock = threading.Lock()
        self._counters: dict[str, int] = dict(counters or {})

    def next(self, kind: str) -> int:
        """Claim the next identifier of ``kind``.  Numbering starts at 1."""
        with self._lock:
            value = self._counters.get(kind, 0) + 1
            self._counters[kind] = value
            return value

    def peek(self, kind: str) -> int:
        """The most recently issued identifier of ``kind``, or 0 if none."""
        with self._lock:
            return self._counters.get(kind, 0)

    def reserve(self, kind: str, value: int) -> None:
        """Guarantee that no future ``next(kind)`` returns ``value`` or below.

        Used when identifiers arrive from outside the allocator — restoring an Episodic
        Memory from its stored rows, where each answer keeps the identifier it was given
        in the run that found it.  Without this the counter would start again at 1
        and re-issue an identifier already in use, and the two answers sharing it would
        be indistinguishable to every API that names one.
        """
        with self._lock:
            if value > self._counters.get(kind, 0):
                self._counters[kind] = value

    def snapshot(self) -> dict[str, int]:
        """The counters, for state capture.

        A run restored from a captured state must not re-issue identifiers it has
        already used, so the counters are part of the state and not derivable from
        it — an object graph records the identifiers that exist, not the ones that
        were skipped by structures that fizzled.
        """
        with self._lock:
            return dict(self._counters)

    def restore(self, counters: dict[str, int]) -> None:
        """Resume numbering from a captured snapshot."""
        with self._lock:
            self._counters = dict(counters)

    def __repr__(self) -> str:
        return f"IdAllocator({self.snapshot()})"


#: The allocator of the run being executed in this context.  There is no default: an
#: identifier is a run's, and code that allocates one outside a run (``next_id`` with
#: nothing bound) raises rather than draw from a counter that belongs to the process.
_CURRENT: ContextVar[IdAllocator] = ContextVar("petacat_id_allocator")


def next_id(kind: str) -> int:
    """Claim the next identifier of ``kind`` from the current allocator."""
    try:
        allocator = _CURRENT.get()
    except LookupError:
        from server.engine.run_binding import NoRunBound

        raise NoRunBound(
            f"a {kind} identifier was claimed with no run bound in this thread; "
            "identifiers belong to a run (EngineContext.scope()), and there is no "
            "process-wide fallback"
        ) from None
    return allocator.next(kind)


def bind_allocator(allocator: IdAllocator) -> Token:
    """Make *allocator* current and return the token that ``unbind_allocator`` undoes.

    For a context manager that binds several things at once (``run_binding.use_run``);
    everything else uses :func:`use_allocator`.
    """
    return _CURRENT.set(allocator)


def unbind_allocator(token: Token) -> None:
    _CURRENT.reset(token)


@contextmanager
def use_allocator(allocator: IdAllocator) -> Iterator[IdAllocator]:
    """Bind ``allocator`` for the duration of the block.

    The previous binding is restored on exit, so an engine call that happens to be
    nested inside another run's call — the service layer holds several runners at
    once — cannot leave the wrong allocator behind it.
    """
    token = _CURRENT.set(allocator)
    try:
        yield allocator
    finally:
        _CURRENT.reset(token)
