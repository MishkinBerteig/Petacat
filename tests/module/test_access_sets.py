"""Read-set / write-set discipline (WP4.2).

Two things have to be true, and they pull in opposite directions.

The sets must be **real** — a read-set that misses the objects a codelet actually
depended on would validate cleanly while the codelet's premises had moved, which is
worse than no tracking at all, because it would look like it was working.

And turning tracking on must **change nothing** about a serial run. Serial execution is
the permanent reference mode that every later phase validates against, so it cannot
acquire different behaviour the moment the parallel machinery is switched on.
"""

from __future__ import annotations

import os
import threading

import pytest

from server.engine.access import (
    KIND_COMPONENT,
    KIND_NODE,
    KIND_OBJECT,
    KIND_STRUCTURE,
    AccessRecorder,
    AccessSet,
    VersionTable,
)
from server.engine.metadata import MetadataProvider
from server.engine.runner import EngineRunner

SEED_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "seed_data",
)


@pytest.fixture(scope="module")
def meta() -> MetadataProvider:
    return MetadataProvider.from_seed_data(SEED_DIR)


def _run(meta, *, tracked: bool, steps: int = 800, seed: int = 42):
    runner = EngineRunner(meta)
    runner.init_mcat("abc", "abd", "mrrjjj", seed=seed)
    if tracked:
        runner.ctx.enable_access_tracking()
    result = runner.run_mcat(max_steps=steps)
    return runner, result


# --- the version table -----------------------------------------------------


def test_unwritten_entities_are_version_zero():
    """No entry until something is written, so the table stays proportional to what
    the run touched rather than to the size of the Workspace."""
    versions = VersionTable()
    assert versions.version((KIND_OBJECT, 1)) == 0
    assert len(versions) == 0


def test_writes_bump_versions():
    versions = VersionTable()
    assert versions.bump((KIND_OBJECT, 1)) == 1
    assert versions.bump((KIND_OBJECT, 1)) == 2
    assert versions.version((KIND_OBJECT, 2)) == 0


def test_versions_are_read_atomically():
    """A read-set is validated all at once, so it must be observed all at once.

    Taking the lock per key would let the table move mid-validation, so the set was
    never all observed at any single instant — and a codelet could be accepted on a
    combination of versions that never simultaneously held.
    """
    versions = VersionTable()
    keys = [(KIND_OBJECT, i) for i in range(50)]
    for key in keys:
        versions.bump(key)
    snapshot = versions.versions(keys)
    assert set(snapshot) == set(keys)
    assert all(v == 1 for v in snapshot.values())


def test_version_table_is_safe_under_concurrent_writes():
    """A bare ``+= 1`` here would lose updates exactly as the identifier counters did,
    and with the same consequence: two writers each believing they were the only one."""
    versions = VersionTable()
    key = (KIND_OBJECT, 7)

    def worker() -> None:
        for _ in range(500):
            versions.bump(key)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert versions.version(key) == 4000


# --- entity keys -----------------------------------------------------------


def test_keys_distinguish_objects_structures_and_nodes(meta):
    runner, _ = _run(meta, tracked=False, steps=900)
    ws = runner.ctx.workspace

    obj = ws.all_objects[0]
    bond = next((b for s in ws.all_strings for b in s.bonds), None)
    node = runner.ctx.slipnet.nodes["plato-a"]

    assert AccessSet.key_for(obj)[0] == KIND_OBJECT
    assert AccessSet.key_for(node) == (KIND_NODE, "plato-a")
    if bond is not None:
        assert AccessSet.key_for(bond)[0] == KIND_STRUCTURE


def test_unrecognised_things_are_not_tracked():
    """Untracked reads cannot cause false conflicts, which is the safe direction."""
    assert AccessSet.key_for(None) is None
    assert AccessSet.key_for("a string") is None
    assert AccessSet.key_for(object()) is None


def test_first_read_of_an_entity_wins():
    """A codelet validates against what it saw when it *began* relying on something.

    Keeping the later version would quietly forgive a change that happened in between,
    which is precisely the change validation exists to catch.
    """
    access = AccessSet()
    access.record_read((KIND_OBJECT, 1), 3)
    access.record_read((KIND_OBJECT, 1), 9)
    assert access.reads[(KIND_OBJECT, 1)] == 3


# --- validation ------------------------------------------------------------


def test_validation_passes_when_nothing_moved():
    recorder = AccessRecorder()
    recorder.begin()
    recorder.versions.bump((KIND_OBJECT, 1))
    recorder.current.record_read((KIND_OBJECT, 1), recorder.versions.version((KIND_OBJECT, 1)))
    assert recorder.validate() is True


def test_validation_fails_when_a_premise_moved():
    """The whole point: a codelet that decided against a Workspace that no longer
    exists must be told so, and the architecture's answer is to fizzle."""
    recorder = AccessRecorder()
    access = recorder.begin()
    key = (KIND_OBJECT, 1)
    access.record_read(key, recorder.versions.version(key))

    recorder.versions.bump(key)  # somebody else wrote it

    assert recorder.validate() is False
    assert recorder.conflicts == 1


def test_an_empty_read_set_always_validates():
    """A codelet that read nothing cannot have been invalidated by anything."""
    recorder = AccessRecorder()
    recorder.begin()
    assert recorder.validate() is True


def test_recorders_do_not_share_a_current_set_across_threads():
    """One recorder, many workers: each must accumulate into its own set.

    Sharing would mix one codelet's reads into another's validation, and the failure
    would be intermittent and attributed to the scheduler.
    """
    recorder = AccessRecorder()
    seen: dict[int, int] = {}

    def worker(index: int) -> None:
        access = recorder.begin()
        for i in range(20):
            access.record_read((KIND_OBJECT, index * 100 + i), 0)
        seen[index] = len(recorder.current.reads)
        recorder.end()

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert set(seen.values()) == {20}


# --- against the real engine -----------------------------------------------


def test_tracking_does_not_change_a_serial_run(meta):
    """Serial execution is the permanent reference mode.

    Compared on the full run outcome and the RNG call count, because the recorder must
    not consume randomness or perturb ordering — only observe.
    """
    plain_runner, plain = _run(meta, tracked=False)
    tracked_runner, tracked = _run(meta, tracked=True)

    assert plain.status == tracked.status
    assert plain.answers == tracked.answers
    assert plain.codelet_count == tracked.codelet_count
    assert plain_runner.ctx.rng.call_count == tracked_runner.ctx.rng.call_count
    assert [e.event_number for e in plain_runner.ctx.trace.events] == [
        e.event_number for e in tracked_runner.ctx.trace.events
    ]


def test_a_serial_run_records_no_conflicts(meta):
    """Nothing runs between a codelet's reads and its commit, so nothing can have moved.

    This is what makes turning tracking on a no-op for behaviour: the validation that
    will cause fizzles under free-running always passes serially.
    """
    runner = EngineRunner(meta)
    runner.init_mcat("abc", "abd", "mrrjjj", seed=42)
    runner.ctx.enable_access_tracking()
    result = runner.run_mcat(max_steps=800)

    assert runner.ctx.access.conflicts == 0
    # Validation happens at each codelet's own commit point; every one of them held.
    assert all(step.premises_held for step in result.steps)


def test_validation_is_meaningful_only_at_the_commit_point(meta):
    """Revalidating a *historical* read-set is guaranteed to fail, by design.

    A read-set answers "were these still the premises when I committed?" — a question
    asked at one instant. Later codelets legitimately move the same entities, so a
    retrospective check reports conflicts that never happened. Worth pinning, because
    a stale-set check is the natural mistake to make when reading this API.
    """
    runner, _ = _run(meta, tracked=True, steps=900)
    recorder = runner.ctx.access
    early = [a for a in recorder.history if a.reads]
    assert early, "the run recorded no read-sets"
    # At least one early set now fails, purely because the run continued.
    assert any(not recorder.validate(a) for a in early)


def test_real_codelets_record_real_sets(meta):
    """A read-set that missed what a codelet depended on would validate cleanly while
    its premises had moved — working-looking and wrong."""
    runner, _ = _run(meta, tracked=True)
    recorder = runner.ctx.access
    summary = recorder.summary()

    assert summary["recorded_codelets"] > 0
    assert summary["tracked_entities"] > 0
    assert summary["mean_read_set"] > 0, "no codelet recorded a read"
    assert summary["mean_write_set"] > 0, "no codelet recorded a write"

    kinds = {
        kind
        for access in recorder.history
        for kind, _ in list(access.reads) + list(access.writes)
    }
    assert KIND_OBJECT in kinds
    assert KIND_STRUCTURE in kinds
    assert KIND_COMPONENT in kinds, "the coderack should appear as a written component"


def test_write_sets_include_the_objects_a_structure_relates(meta):
    """Building a bond changes its two objects as much as the bond itself.

    A letter that has just acquired a bond is not the letter a concurrent scout read a
    moment ago, and tracking only the structure would let that scout's decision stand.
    """
    runner, _ = _run(meta, tracked=True, steps=1200)
    recorder = runner.ctx.access

    with_structure_writes = [
        a for a in recorder.history
        if any(kind == KIND_STRUCTURE for kind, _ in a.writes)
    ]
    assert with_structure_writes, "no structure was built or broken in this run"
    assert any(
        any(kind == KIND_OBJECT for kind, _ in a.writes) for a in with_structure_writes
    ), "structure writes never recorded the objects they relate"


def test_access_sets_are_inspectable(meta):
    """The plan asks for the sets to be recorded *and inspectable*."""
    runner, _ = _run(meta, tracked=True)
    access = runner.ctx.access.history[-1]
    summary = access.summary()

    assert set(summary) == {"reads", "writes", "read_count", "write_count"}
    assert all(isinstance(entry, str) for entry in summary["reads"] + summary["writes"])


def test_history_is_bounded(meta):
    """An unbounded log would be exactly the write-only accumulation Phase 0 removed."""
    runner, _ = _run(meta, tracked=True, steps=2500)
    recorder = runner.ctx.access
    assert len(recorder.history) <= recorder.history_limit


def test_tracking_can_be_turned_off_again(meta):
    runner, _ = _run(meta, tracked=True, steps=100)
    assert runner.ctx.access is not None
    runner.ctx.enable_access_tracking(False)
    assert runner.ctx.access is None
    assert runner.ctx.track_access is False
    runner.run_mcat(max_steps=100)  # must still run
