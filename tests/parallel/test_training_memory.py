"""The episode memory of a Training: copy at start, merge at finish.

These hold the pieces that make shared memory reproducible without a database: descriptions
survive the JSON encoding used for storage and the pickle used for transport, a merge skips
what the episode already holds, a run's copy is independent of the master, and a worker
reaches a task's version from its cache plus the task's tail (or asks for a snapshot).
"""

from __future__ import annotations

import os
import pickle

import pytest

from server.engine.memory import EpisodicMemory
from server.engine.metadata import MetadataProvider
from server.engine.numeric.backend import use_backend
from server.engine.runner import EngineRunner
from server.services import training_memory as tm

SEED_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "seed_data")


@pytest.fixture(scope="module")
def meta():
    return MetadataProvider.from_seed_data(SEED_DIR)


def run_into(meta, memory, seed, problem=("abc", "abd", "xyz"), steps=2500):
    base_a, base_s = len(memory.answers), len(memory.snags)
    runner = EngineRunner(meta)
    with use_backend("off"):
        runner.init_mcat(*problem, seed=seed, memory=memory)
        runner.run_mcat(max_steps=steps)
    return runner, tm.additions_of(memory, base_a, base_s)


@pytest.fixture(scope="module")
def additions(meta):
    """Additions of a few runs started from the same (empty) memory."""
    out = []
    for seed in (1, 2, 3):
        mem = tm.copy_for_run(EpisodicMemory())
        _, adds = run_into(meta, mem, seed)
        out.append(adds)
    return out


def test_descriptions_round_trip_through_json_and_pickle(additions):
    adds = next(a for a in additions if a.answers)
    answers, snags = tm.encode_additions(adds)
    import json

    again = tm.decode_additions(json.loads(json.dumps(answers)), json.loads(json.dumps(snags)))
    assert [vars(a) for a in again.answers] == [vars(a) for a in adds.answers]
    assert [vars(s) for s in again.snags] == [vars(s) for s in adds.snags]
    assert all(isinstance(a.problem, tuple) for a in again.answers)
    viaPickle = pickle.loads(tm.dump_additions(adds))
    assert [vars(a) for a in viaPickle.answers] == [vars(a) for a in adds.answers]


def test_a_merge_skips_what_the_episode_already_holds(additions):
    adds = next(a for a in additions if a.answers)
    master = EpisodicMemory()
    assert tm.apply_merge(master, adds)[0] == len(adds.answers)
    before = (len(master.answers), len(master.snags))
    dup = pickle.loads(tm.dump_additions(adds))
    assert tm.apply_merge(master, dup) == (0, 0)  # the same ideas again: deduplicated
    assert (len(master.answers), len(master.snags)) == before


def test_a_merge_restamps_ids_in_the_masters_numbering(meta):
    master = EpisodicMemory()
    for seed in (1, 2, 3):
        copy = tm.copy_for_run(master)
        _, adds = run_into(meta, copy, seed)
        tm.apply_merge(master, adds)
    ids = [a.answer_id for a in master.answers_oldest_first]
    assert ids == list(range(1, len(ids) + 1))
    assert master.ids.peek("answer") == len(ids)


def test_a_runs_copy_is_independent_of_the_master(meta):
    master = EpisodicMemory()
    copy = tm.copy_for_run(master)
    run_into(meta, copy, 1)
    assert len(copy.answers) >= 1 and master.answers == [] and master.ids.peek("answer") == 0


def test_a_serial_episode_equals_copy_and_merge_one_run_at_a_time(meta):
    problem = ("abc", "abd", "xyz")
    shared, merged = EpisodicMemory(), EpisodicMemory()
    for seed in range(1, 6):
        r1, _ = run_into(meta, shared, seed)
        copy = tm.copy_for_run(merged)
        r2, adds = run_into(meta, copy, seed)
        tm.apply_merge(merged, adds)
        assert (r1.status, r1.ctx.codelet_count) == (r2.status, r2.ctx.codelet_count)
    assert tm.memory_fingerprint(shared) == tm.memory_fingerprint(merged)


def test_a_worker_reaches_a_version_from_its_cache_and_the_tail(additions):
    tm.forget_worker_cache()
    master = EpisodicMemory()
    blobs = {}
    for v, adds in enumerate(additions, start=1):
        blobs[v] = tm.dump_additions(adds)
        tm.apply_merge(master, adds)

    ref = tm.MemoryRef(7, "e", 2, 0, [blobs[1], blobs[2]])
    first = tm.worker_master(ref)  # from empty, whole tail
    ref3 = tm.MemoryRef(7, "e", 3, 1, [blobs[2], blobs[3]])
    second = tm.worker_master(ref3)  # cached v2 + the last merge
    assert second is first
    assert tm.memory_fingerprint(second) == tm.memory_fingerprint(master)

    behind = tm.MemoryRef(7, "other-epoch", 3, 2, [blobs[3]])
    with pytest.raises(tm.NeedSnapshot):
        tm.worker_master(behind)
    ahead = tm.MemoryRef(7, "e", 1, 0, [blobs[1]])
    with pytest.raises(tm.NeedSnapshot):
        tm.worker_master(ahead)
    snap = tm.MemoryRef(7, "other-epoch", 3, snapshot=tm.snapshot_blob(master))
    assert tm.memory_fingerprint(tm.worker_master(snap)) == tm.memory_fingerprint(master)
    tm.forget_worker_cache()
