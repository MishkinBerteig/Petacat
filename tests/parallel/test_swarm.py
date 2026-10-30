"""The swarm executes runs *exactly*: every outcome equals the in-process serial run.

What these tests defend is the swarm's one promise: spreading runs over processes changes
**nothing** about any run.  A swarm outcome has to equal the serial outcome for the same
problem, seed, parameters and numeric backend -- stopping state, codelet count, answers,
temperature and answer quality -- and an episode has to carry its memory exactly as
``scripts/compare_to_metacat.py`` does.  Throughput is measured elsewhere
(``scripts/bench_swarm.py``); correctness is not allowed to depend on it.
"""

from __future__ import annotations

import json
import os
import threading

import pytest

from server.engine.hashing import config_hash
from server.engine.memory import EpisodicMemory
from server.engine.metadata import MetadataProvider
from server.engine.numeric.backend import use_backend
from server.engine.runner import STATUS_ANSWER_FOUND, EngineRunner
from server.parallel import qos
from server.parallel.swarm import (
    SEED_DIR,
    EpisodeTask,
    RunTask,
    Swarm,
    default_backend,
    default_swarm_status,
    run_inprocess,
)

# Keep runs short: this is a fidelity test, and a capped run is as good a witness as a
# finished one so long as swarm and serial agree on where it stopped.
MAX_STEPS = 1500


def _demo_problems() -> list[tuple]:
    path = os.path.join(SEED_DIR, "demo_problems.json")
    with open(path) as fh:
        demo = json.load(fh)
    seen, out = set(), []
    for p in demo:
        key = (
            p["initial"], p["modified"], p["target"],
            p.get("answer") if p["mode"] == "justification" else None,
        )
        if key not in seen:
            seen.add(key)
            out.append(key)
    return out


@pytest.fixture(scope="module")
def meta() -> MetadataProvider:
    return MetadataProvider.from_seed_data(SEED_DIR)


@pytest.fixture(scope="module")
def swarm(meta):
    with Swarm(workers=4, meta=meta) as sw:
        yield sw


def test_swarm_outcomes_equal_serial_for_demo_problems_and_seeds(swarm, meta):
    """Several demo problems (discovery and justification) x seeds: swarm == serial."""
    problems = _demo_problems()
    # Spread across the list, discovery and justification both.
    chosen = problems[:: max(1, len(problems) // 6)][:6]
    tasks = [
        RunTask(i, m, t, a, seed, MAX_STEPS)
        for (i, m, t, a) in chosen
        for seed in (1, 2, 3)
    ]
    swarm_out = swarm.map(tasks, meta=meta)
    assert [o.index for o in swarm_out] == list(range(len(tasks)))
    for task, got in zip(tasks, swarm_out):
        want = run_inprocess(task, meta)
        assert got.error is None, got.error
        assert got.stopping_state == want.stopping_state, task
        assert got.codelets == want.codelets, task
        assert got.answers == want.answers, task
        assert got.fingerprint() == want.fingerprint(), task


def test_swarm_matches_a_hand_written_serial_loop(swarm, meta):
    """Not only 'the same helper twice': agree with the plain runner loop."""
    task = RunTask("abc", "abd", "mrrjjj", None, 42, 3000, backend="numpy")
    got = swarm.run(task, meta=meta)
    with use_backend("numpy"):
        runner = EngineRunner(meta)
        runner.init_mcat("abc", "abd", "mrrjjj", seed=42)
        result = runner.run_mcat(max_steps=3000)
        answer = runner.ctx.workspace.answer_string
        text = answer.text if answer else ""
    assert got.stopping_state == f"{runner.status}:{text}"
    assert got.codelets == result.codelet_count
    assert got.answers == result.answers


def test_parameter_overrides_and_both_cpu_backends_are_exact(swarm, meta):
    tasks = [
        RunTask("abc", "abd", "ijk", None, 5, MAX_STEPS, parameters={"update_cycle_length": 10}),
        RunTask("abc", "abd", "ijk", None, 5, MAX_STEPS, backend="off"),
        RunTask("abc", "abd", "ijk", None, 5, MAX_STEPS, backend="numpy"),
    ]
    for task, got in zip(tasks, swarm.map(tasks, meta=meta)):
        assert got.fingerprint() == run_inprocess(task, meta).fingerprint(), task


def test_imap_unordered_yields_every_task_once(swarm, meta):
    tasks = [RunTask("abc", "abd", "ijk", None, s, 400) for s in range(1, 13)]
    seen = sorted(o.index for o in swarm.imap_unordered(tasks, meta=meta))
    assert seen == list(range(12))


def test_tag_and_default_backend_travel_with_the_task(swarm, meta):
    out = swarm.map([RunTask("abc", "abd", "ijk", None, 1, 200, tag={"k": 1})], meta=meta)
    assert out[0].tag == {"k": 1}
    assert swarm.backend == default_backend(meta) != "mlx"


def test_a_failing_run_is_an_outcome_not_a_crash(swarm, meta):
    tasks = [
        RunTask("abc", "abd", "ijk", None, 1, 200),
        RunTask("abc", "abd", "ijk", None, 2, 200, executor="no-such-executor"),
        RunTask("abc", "abd", "ijk", None, 3, 200),
    ]
    out = swarm.map(tasks, meta=meta)
    assert [o.error is None for o in out] == [True, False, True]
    assert out[1].status == "error"


def _episode_by_hand(meta, task: EpisodeTask) -> list[str]:
    """``scripts/compare_to_metacat.py::run_episode``, transcribed."""
    memory = EpisodicMemory()
    states = []
    with use_backend(task.backend):
        for i in range(task.runs):
            before = len(memory.answers)
            runner = EngineRunner(meta)
            runner.init_mcat(
                task.initial, task.modified, task.target, seed=task.first_seed + i, memory=memory
            )
            runner.run_mcat(max_steps=task.max_steps)
            answered = len(memory.answers) > before and runner.status == STATUS_ANSWER_FOUND
            if answered:
                answer = runner.ctx.workspace.answer_string
                states.append(answer.text if answer else "*NONE*")
            elif runner.ctx.codelet_count >= task.max_steps:
                states.append("*CAP*")
            else:
                states.append("*NONE*")
    return states


def test_episode_in_swarm_equals_episode_in_process(swarm, meta):
    tasks = [
        EpisodeTask("abc", "abd", "ijk", first_seed=100, runs=4, max_steps=MAX_STEPS, backend="numpy"),
        EpisodeTask("abc", "abd", "mrrjjj", first_seed=7, runs=3, max_steps=MAX_STEPS, backend="numpy"),
    ]
    got = swarm.map(tasks, meta=meta)
    for task, episode in zip(tasks, got):
        assert episode.error is None, episode.error
        assert episode.states == _episode_by_hand(meta, task)
        assert episode.fingerprint() == run_inprocess(task, meta).fingerprint()
        assert len(episode.runs) == task.runs


def test_episode_memory_really_is_shared_between_its_runs(swarm, meta):
    """Runs of an episode differ from the same seeds run with fresh memory."""
    ep = EpisodeTask("abc", "abd", "ijk", first_seed=1, runs=4, max_steps=MAX_STEPS, backend="numpy")
    shared = swarm.run(ep, meta=meta)
    fresh = swarm.map(
        [RunTask("abc", "abd", "ijk", None, 1 + i, MAX_STEPS, backend="numpy") for i in range(4)],
        meta=meta,
    )
    assert shared.runs[0].fingerprint()[:-1] == fresh[0].fingerprint()[:-1]  # run 0: same memory
    assert shared.memory_answers >= 1


# -- QoS ----------------------------------------------------------------------------


def test_qos_calls_are_harmless():
    """Setting QoS never raises, in any thread, with any value; off macOS it is a no-op."""
    results = []

    def body():
        results.append(qos.set_thread_qos(qos.USER_INITIATED))
        results.append(qos.set_thread_qos(0xDEAD))  # not a QoS class: swallowed
        results.append(qos.set_thread_qos(qos.UTILITY))
        qos.current_thread_qos()

    t = threading.Thread(target=body)
    t.start()
    t.join()
    assert len(results) == 3
    assert all(isinstance(r, qos.QosResult) for r in results)
    if not qos.available():
        assert not any(r.applied for r in results)


def test_describe_core_tiers_accounts_for_every_core():
    tiers = qos.describe_core_tiers()
    assert tiers.tiers and tiers.logical_cores >= 1
    assert sum(t.logical_cpus for t in tiers.tiers) in (tiers.logical_cores, tiers.logical_cores - 0)


def test_swarm_without_qos_gives_identical_outcomes(meta):
    task = RunTask("abc", "abd", "ijk", None, 9, MAX_STEPS, backend="numpy")
    with Swarm(workers=2, meta=meta, qos=False) as plain, Swarm(workers=2, meta=meta, qos=True) as placed:
        assert plain.run(task).fingerprint() == placed.run(task).fingerprint()
        assert all(w["qos_applied"] is None for w in plain.worker_info())
        if qos.available():
            assert all(w["qos"] == "USER_INITIATED" for w in placed.worker_info())


# -- configuration ---------------------------------------------------------------------


def test_config_change_reinitialises_workers(meta):
    """A different configuration re-initialises the workers, and runs follow it."""
    other = meta.with_overrides({"update_cycle_length": 9})
    assert config_hash(other) != config_hash(meta)
    task = RunTask("abc", "abd", "mrrjjj", None, 3, 2000, backend="numpy")
    with Swarm(workers=2, meta=meta) as sw:
        first = sw.run(task)
        assert {w["config_hash"] for w in sw.worker_info()} == {config_hash(meta)}
        assert sw.configure(meta) is False  # same hash: nothing to do
        assert sw.configure(other) is True
        assert {w["config_hash"] for w in sw.worker_info()} == {config_hash(other)}
        second = sw.run(task)
        assert second.fingerprint() == run_inprocess(task, other).fingerprint()
        assert first.fingerprint() == run_inprocess(task, meta).fingerprint()
        assert sw.rebinds == 1


def test_idle_swarm_rebinds_on_a_call_with_different_metadata(meta):
    other = meta.with_overrides({"update_cycle_length": 11})
    task = RunTask("abc", "abd", "ijk", None, 4, MAX_STEPS, backend="numpy")
    with Swarm(workers=2, meta=meta) as sw:
        got = sw.run(task, meta=other)
        assert sw.config_hash() == config_hash(other)
        assert got.fingerprint() == run_inprocess(task, other).fingerprint()


def test_busy_swarm_ships_metadata_with_the_tasks_of_a_different_config(meta):
    """While another job is in flight the pool is not rebound; the new metadata rides along."""
    other = meta.with_overrides({"update_cycle_length": 12})
    task = RunTask("abc", "abd", "ijk", None, 6, MAX_STEPS, backend="numpy")
    with Swarm(workers=2, meta=meta) as sw:
        stream = sw.imap_unordered(RunTask("abc", "abd", "ijk", None, s, 300) for s in range(1, 9))
        next(stream)  # a job is now in flight
        got = sw.run(task, meta=other)
        assert sw.config_hash() == config_hash(meta) and sw.rebinds == 0
        assert got.fingerprint() == run_inprocess(task, other).fingerprint()
        assert len(list(stream)) == 7


def test_metadata_pickles_cheaply(meta):
    import pickle
    import time

    began = time.perf_counter()
    blob = pickle.dumps(meta, protocol=pickle.HIGHEST_PROTOCOL)
    restored = pickle.loads(blob)
    elapsed = time.perf_counter() - began
    assert config_hash(restored) == config_hash(meta)
    assert elapsed < 0.5


def test_default_status_does_not_start_a_pool():
    status = default_swarm_status()
    assert status["workers"] >= 1 and status["start_method"] == "forkserver"


def test_a_fresh_swarm_given_no_metadata_runs_on_the_seed_data(meta):
    """The first call on a pool constructed without metadata binds the seed data.

    The tasks of that call must name the configuration the workers were started with.
    They once carried the empty hash read before ``_start`` bound it, and every worker
    refused them ("no metadata for config ''"); the other tests never saw it because
    each passes ``meta`` explicitly.
    """
    swarm = Swarm(workers=2)
    try:
        outcome = swarm.map([RunTask("abc", "abd", "xyz", seed=7, max_steps=3000)])[0]
    finally:
        swarm.shutdown()
    assert outcome.error is None, outcome.error
    expected = run_inprocess(
        RunTask("abc", "abd", "xyz", seed=7, max_steps=3000, backend=default_backend(meta)),
        meta,
    )
    assert outcome.fingerprint() == expected.fingerprint()
