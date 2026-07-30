"""Identifiers depend on the run, not on the process's history (WP0.3, defect D3).

Before ``server/engine/ids.py`` existed, five classes carried class-level ``_next_id``
counters incremented in place.  The same ``(problem, seed)`` executed three times in
one process produced identical cognition — the RNG is seeded per run — but
``event_number`` sequences starting at 1, 19 and 41, because the counter carried over
from whatever ran before.

That matters beyond tidiness.  ``TraceEvent.event_number`` is persisted to
``trace_events.event_number`` and is the ordering key of ``get_trace_events_from_db``,
so process history leaked into the stored record of a run.  The read-modify-write is
also non-atomic, which makes the same counters a data race once Workstream B runs
codelets concurrently.

These tests pin the property the fix establishes: run *n* of a process is
indistinguishable from run 1.
"""

from __future__ import annotations

import os
import threading

import pytest

from server.engine.ids import IdAllocator, current_allocator, use_allocator
from server.engine.metadata import MetadataProvider
from server.engine.runner import EngineRunner

SEED_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "seed_data",
)

PROBLEM = ("abc", "abd", "xyz")
SEED = 42
STEPS = 300


@pytest.fixture(scope="module")
def meta() -> MetadataProvider:
    return MetadataProvider.from_seed_data(SEED_DIR)


def _run(meta: MetadataProvider) -> dict:
    """Execute a fixed run and return the identifiers it produced."""
    runner = EngineRunner(meta)
    runner.init_mcat(*PROBLEM, seed=SEED)
    runner.run_mcat(max_steps=STEPS)
    ctx = runner.ctx
    return {
        "event_numbers": [e.event_number for e in ctx.trace.events],
        "codelet_ids": sorted(
            c.id for b in ctx.coderack.bins for c in b.codelets
        ),
        "object_ids": sorted(o.id for o in ctx.workspace.all_objects),
        "codelet_count": ctx.codelet_count,
    }


def test_repeated_runs_in_one_process_produce_identical_identifiers(meta):
    """Three runs of the same problem and seed, back to back, must agree.

    This is the exact scenario that failed before the fix, and the reason the
    numbers in the plan's defect D3 are 1, 19 and 41.
    """
    first, second, third = _run(meta), _run(meta), _run(meta)

    assert first["event_numbers"] == second["event_numbers"] == third["event_numbers"]
    assert first["codelet_ids"] == second["codelet_ids"] == third["codelet_ids"]
    assert first["object_ids"] == second["object_ids"] == third["object_ids"]


def test_event_numbering_starts_at_one_for_every_run(meta):
    """Numbering restarts per run rather than continuing from process-wide state."""
    for _ in range(3):
        result = _run(meta)
        if result["event_numbers"]:
            assert result["event_numbers"][0] == 1


def test_trace_event_numbers_are_dense_and_ordered(meta):
    """Every event number between the first and last is used, exactly once.

    ``event_number`` is an ordering key in the persisted record, so gaps or repeats
    would show up as reordered or missing history in the trace view.
    """
    numbers = _run(meta)["event_numbers"]
    assert numbers == sorted(numbers)
    assert len(numbers) == len(set(numbers))
    assert numbers == list(range(1, len(numbers) + 1))


def test_concurrent_runs_do_not_take_numbers_from_each_other(meta):
    """Two runners stepping in different threads keep separate numbering.

    The allocator binding is a ``ContextVar``, so each thread starts from its own
    binding.  A module global would not survive this test, and Workstream B will run
    exactly this shape.
    """
    results: dict[int, dict] = {}

    def worker(index: int) -> None:
        results[index] = _run(meta)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(results) == 4
    reference = results[0]
    for index in range(1, 4):
        assert results[index]["event_numbers"] == reference["event_numbers"]
        assert results[index]["object_ids"] == reference["object_ids"]


# --- the allocator itself --------------------------------------------------


def test_allocator_numbers_each_kind_independently():
    alloc = IdAllocator()
    assert [alloc.next("a"), alloc.next("a"), alloc.next("b")] == [1, 2, 1]


def test_allocator_snapshot_and_restore_resume_numbering():
    """A run restored from a captured state must not re-issue identifiers.

    Which identifiers were consumed is not derivable from the restored object graph:
    a structure that fizzled took a number and left nothing behind.  So the counters
    travel with the state.  WP3.4 depends on this.
    """
    alloc = IdAllocator()
    alloc.next("structure")
    alloc.next("structure")
    saved = alloc.snapshot()

    resumed = IdAllocator()
    resumed.restore(saved)
    assert resumed.next("structure") == 3


def test_allocator_binding_is_restored_after_use():
    """Nested bindings unwind, so one runner cannot leave its allocator behind."""
    outer = current_allocator()
    inner = IdAllocator()
    with use_allocator(inner):
        assert current_allocator() is inner
    assert current_allocator() is outer


def test_allocator_is_safe_under_concurrent_increment():
    """No identifier is issued twice, which the bare ``+= 1`` could not promise.

    Under the GIL this is unlikely to fail; under free-threaded CPython the
    read-modify-write it replaces is a genuine race.  The lock is what makes the
    guarantee independent of which interpreter build is running.
    """
    alloc = IdAllocator()
    issued: list[list[int]] = []

    def worker() -> None:
        issued.append([alloc.next("codelet") for _ in range(500)])

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    flat = [n for chunk in issued for n in chunk]
    assert sorted(flat) == list(range(1, 4001))
