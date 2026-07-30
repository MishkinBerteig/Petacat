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
  the one component that deliberately outlives a run: within a Training Session it
  accumulates answers across many runs, and ``POST /api/memory/compare`` looks answers
  up by ``answer_id``.  Per-run numbering there would hand two different answers in
  one session the same identifier.  ``EpisodicMemory`` therefore carries its own
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

When nothing is bound — a structure constructed directly in a unit test, or the
service layer rehydrating episodic memory outside any run — allocation falls back to
a process-wide default.  That is the old behaviour, kept deliberately for the case
where there is no run for an identifier to depend on.  Inside a run the run's own
allocator always wins, which is the property WP0.3 exists to establish.
"""

from __future__ import annotations

import threading
from contextlib import contextmanager
from contextvars import ContextVar
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


#: Allocator used when no run is bound.  See the module docstring: this is for
#: identifiers with no run to belong to, not a convenience for engine code.
_DEFAULT = IdAllocator()

_CURRENT: ContextVar[IdAllocator] = ContextVar("petacat_id_allocator", default=_DEFAULT)


def current_allocator() -> IdAllocator:
    """The allocator identifiers should be drawn from right now."""
    return _CURRENT.get()


def next_id(kind: str) -> int:
    """Claim the next identifier of ``kind`` from the current allocator."""
    return _CURRENT.get().next(kind)


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
