"""A run is bound to its own configuration, Themespace and clock (round 2, stage 2).

``WorkspaceStructure._meta`` and ``._themespace`` used to be class attributes assigned by
``init_mcat``, so creating a second run changed the first: ``abc -> abd; xyz`` seed 7 went
from 2,470 codelets to 1,559 when a second run with the *same* configuration was created
before it finished, and a second run with another configuration made it crash.  These tests
hold the property the fix establishes: **every run is identical to the same run alone**,
whatever else is alive in the process, interleaved on one thread, on parallel threads (the
threads here run *different problems*, which is what the older concurrency test did not),
under the speculative executor, beside a review inspector, and under a different
configuration.

"Identical" is everything an observer can see: the codelet sequence, the answers, the status,
every random draw, every Trace event, and the final state graph.
"""

from __future__ import annotations

import contextvars
import dataclasses
import hashlib
import json
import os
import threading

import pytest

from server.engine.ids import next_id
from server.engine.memory import EpisodicMemory
from server.engine.metadata import ConfigurationRequired, MetadataProvider
from server.engine.run_binding import (
    NoRunBound,
    RunBinding,
    RunConstants,
    constants,
    current,
)
from server.engine.runner import EngineRunner
from server.engine.state_graph import capture_run_state, restore_run_state

pytestmark = pytest.mark.numeric_matrix

SEED_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "seed_data",
)

CAP = 1200

#: The two that went wrong in the lead's reproduction, and others that build bridges, groups
#: and rules, with their seeds.
PAIRS = [
    ((("abc", "abd", "xyz"), 7), (("aabc", "aabd", "ijk"), 8)),
    ((("ace", "acf", "xyz"), 9), (("abc", "qbc", "ijkk"), 10)),
    ((("abc", "abd", "mrrjjj"), 1), (("rst", "rsu", "xyz"), 2)),
]


@pytest.fixture(scope="module")
def meta() -> MetadataProvider:
    return MetadataProvider.from_standard_configuration(SEED_DIR)


@pytest.fixture(scope="module")
def other_meta(meta) -> MetadataProvider:
    """Another configuration: three coefficients that structures read as they compute."""
    coefficients = dict(meta.formula_coefficients)
    coefficients["weakness_exponent"] = 0.9
    coefficients["bond_degree_of_assoc_scale"] = 7
    coefficients["description_local_support_1"] = 20.0
    params = dict(meta.params)
    params["max_theme_activation"] = 80
    return dataclasses.replace(meta, formula_coefficients=coefficients, params=params)


def _make(meta, problem, seed) -> EngineRunner:
    runner = EngineRunner(meta)
    runner.init_mcat(*problem, seed=seed, memory=EpisodicMemory())
    return runner


def _fingerprint(runner: EngineRunner, codelets: list) -> dict:
    ctx = runner.ctx
    state = json.dumps(capture_run_state(ctx), sort_keys=True, default=str)
    return {
        "codelets": codelets,
        "codelet_count": ctx.codelet_count,
        "draws": ctx.rng.call_count,
        "status": runner.status,
        "answers": list(runner._answers),
        "events": [(e.event_number, type(e).__name__, e.codelet_count) for e in ctx.trace.events],
        "state": hashlib.sha256(state.encode()).hexdigest(),
    }


def _step(runner: EngineRunner, log: list) -> bool:
    """One codelet.  False once the run is over."""
    result = runner.step_mcat()
    log.append(result.codelet_type)
    return not (result.answer_found or result.gave_up) and runner.ctx.codelet_count < CAP


def _alone(meta, problem, seed) -> dict:
    runner = _make(meta, problem, seed)
    log: list = []
    while _step(runner, log):
        pass
    runner.finish()
    return _fingerprint(runner, log)


def _finish(runner: EngineRunner, log: list) -> dict:
    while _step(runner, log):
        pass
    runner.finish()
    return _fingerprint(runner, log)


# -- interleaved on one thread -------------------------------------------------------------


@pytest.mark.parametrize("pair", range(len(PAIRS)))
def test_creating_a_second_run_with_the_same_configuration_does_not_change_the_first(
    meta, pair
):
    (pa, sa), (pb, sb) = PAIRS[pair]
    alone_a, alone_b = _alone(meta, pa, sa), _alone(meta, pb, sb)

    a, b = _make(meta, pa, sa), _make(meta, pb, sb)  # B is created before A is stepped
    got_a = _finish(a, [])
    got_b = _finish(b, [])

    assert got_a == alone_a
    assert got_b == alone_b


@pytest.mark.parametrize("pair", range(len(PAIRS)))
def test_creating_a_second_run_under_another_configuration_does_not_change_the_first(
    meta, other_meta, pair
):
    (pa, sa), (pb, sb) = PAIRS[pair]
    alone_a, alone_b = _alone(meta, pa, sa), _alone(other_meta, pb, sb)
    assert alone_a["codelets"] != _alone(other_meta, pa, sa)["codelets"]  # the edit matters

    a, b = _make(meta, pa, sa), _make(other_meta, pb, sb)
    got_a = _finish(a, [])
    got_b = _finish(b, [])

    assert got_a == alone_a
    assert got_b == alone_b


@pytest.mark.parametrize("pair", range(len(PAIRS)))
def test_two_runs_stepped_alternately_each_equal_the_run_alone(meta, other_meta, pair):
    (pa, sa), (pb, sb) = PAIRS[pair]
    alone_a, alone_b = _alone(meta, pa, sa), _alone(other_meta, pb, sb)

    a, b = _make(meta, pa, sa), _make(other_meta, pb, sb)
    log_a: list = []
    log_b: list = []
    live_a = live_b = True
    while live_a or live_b:
        if live_a:
            live_a = _step(a, log_a)
        if live_b:
            live_b = _step(b, log_b)
    a.finish()
    b.finish()

    assert _fingerprint(a, log_a) == alone_a
    assert _fingerprint(b, log_b) == alone_b


def test_a_run_stepped_inside_another_runs_step_leaves_it_as_it_found_it(meta, other_meta):
    """The nesting the review service produced: an inspector stepped while a live run is
    in the middle of a call (here, from inside a codelet's own step)."""
    (pa, sa), (pb, sb) = PAIRS[0]
    alone_a = _alone(meta, pa, sa)
    alone_b = _alone(other_meta, pb, sb)

    a, b = _make(meta, pa, sa), _make(other_meta, pb, sb)
    log_a: list = []
    log_b: list = []
    original = a._execute_codelet
    calls = {"n": 0}

    def execute_then_step_b(codelet):
        original(codelet)
        calls["n"] += 1
        if calls["n"] % 5 == 0:
            _step(b, log_b)  # B is stepped while A's step is under way

    a._execute_codelet = execute_then_step_b
    got_a = _finish(a, log_a)
    got_b = _finish(b, log_b)

    assert got_a == alone_a
    assert got_b == alone_b


# -- the review inspector, beside a live run ------------------------------------------------


def test_an_open_inspector_does_not_change_a_live_run(meta):
    """An inspector is a runner restored from a capture of another run, stepped while the
    live run is in flight.  The live run is identical to itself alone, and the inspector
    follows the run it was restored from."""
    (pa, sa), (pc, sc) = PAIRS[0]
    alone_a = _alone(meta, pa, sa)

    # The run the inspector inspects: stopped at codelet 120, captured.
    recorded = _make(meta, pc, sc)
    log_c: list = []
    while recorded.ctx.codelet_count < 120:
        _step(recorded, log_c)
    state = capture_run_state(recorded.ctx)
    rest_of_c = []
    reference = EngineRunner(meta)
    reference.init_mcat(*pc, seed=sc, memory=EpisodicMemory())
    restore_run_state(reference, state)
    while reference.ctx.codelet_count < 300:
        rest_of_c.append(reference.step_mcat().codelet_type)

    a = _make(meta, pa, sa)
    log_a: list = []
    for _ in range(60):
        _step(a, log_a)
    inspector = EngineRunner(meta)  # opened while A is live
    inspector.init_mcat(*pc, seed=sc, memory=EpisodicMemory())
    restore_run_state(inspector, state)
    seen = []
    for _ in range(len(rest_of_c)):
        seen.append(inspector.step_mcat().codelet_type)
        _step(a, log_a)  # A keeps going between the inspector's steps

    got_a = _finish(a, log_a)
    assert got_a == alone_a
    assert seen == rest_of_c


# -- parallel threads, different problems --------------------------------------------------


def test_parallel_threads_running_different_problems_each_equal_the_run_alone(
    meta, other_meta
):
    """The older concurrency test ran one problem in every thread, which any shared
    binding passes.  These run different problems, and different configurations, at once."""
    jobs = [
        (meta, *PAIRS[0][0]),
        (other_meta, *PAIRS[0][1]),
        (meta, *PAIRS[1][0]),
        (other_meta, *PAIRS[1][1]),
        (meta, *PAIRS[2][0]),
        (other_meta, *PAIRS[2][1]),
    ]
    alone = [_alone(m, p, s) for m, p, s in jobs]

    got: dict[int, dict] = {}
    errors: list = []
    start = threading.Barrier(len(jobs))

    def work(index: int) -> None:
        m, p, s = jobs[index]
        try:
            runner = _make(m, p, s)
            start.wait()
            got[index] = _finish(runner, [])
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)
            start.abort()

    threads = [threading.Thread(target=work, args=(i,)) for i in range(len(jobs))]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, errors
    for index in range(len(jobs)):
        assert got[index] == alone[index], index


def test_a_thread_started_inside_a_run_does_not_need_to_inherit_its_context(meta):
    """On the GIL build a new thread starts with an empty context.  The binding is installed
    by whoever runs engine code, so a worker that opens ``ctx.scope()`` has its own run."""
    runner = _make(meta, *PAIRS[0][0])
    seen: dict = {}

    def worker():
        with runner.ctx.scope():
            seen["constants"] = constants()
            seen["id"] = next_id("structure")

    t = threading.Thread(target=worker)
    t.start()
    t.join()
    assert seen["constants"] is runner.ctx.binding.constants
    assert seen["id"] >= 1


# -- speculative workers -----------------------------------------------------------------


def test_two_speculative_runs_in_one_process_each_equal_the_run_alone(meta, other_meta):
    """Two engines with worker threads at once, different problems and configurations.
    (The engine's write guard used to be a module global: one engine per process.)"""
    from server.parallel.speculative.compare import diff, run_record

    jobs = [
        (meta, (*PAIRS[0][0][0], None), PAIRS[0][0][1]),
        (other_meta, (*PAIRS[1][1][0], None), PAIRS[1][1][1]),
    ]
    alone = [run_record(m, p, s, "spec", workers=2, max_steps=500, use_qos=False)
             for m, p, s in jobs]
    reference = [run_record(m, p, s, "ssr", max_steps=500) for m, p, s in jobs]
    for a, r in zip(alone, reference):
        assert diff(r, a) == []

    got: dict[int, object] = {}
    errors: list = []
    start = threading.Barrier(len(jobs))

    def work(i: int) -> None:
        m, p, s = jobs[i]
        try:
            start.wait()
            got[i] = run_record(m, p, s, "spec", workers=2, max_steps=500, use_qos=False)
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=work, args=(i,)) for i in range(len(jobs))]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors, errors
    for i in range(len(jobs)):
        assert diff(alone[i], got[i]) == [], i


# -- nothing falls back ---------------------------------------------------------------------


def _unbound(fn):
    """Run *fn* in an empty context: no run is bound in it."""
    return contextvars.Context().run(fn)


def test_engine_code_with_no_run_bound_raises_instead_of_falling_back():
    with pytest.raises(NoRunBound):
        _unbound(current)
    with pytest.raises(NoRunBound):
        _unbound(constants)
    with pytest.raises(NoRunBound):
        _unbound(lambda: next_id("structure"))
    assert issubclass(NoRunBound, ConfigurationRequired)


def test_a_structure_cannot_be_made_with_no_run_bound(meta):
    from server.engine.workspace_structures import WorkspaceStructure

    with pytest.raises(NoRunBound):
        _unbound(WorkspaceStructure)


def test_nothing_run_wide_is_left_on_the_classes():
    from server.engine.workspace_structures import WorkspaceStructure

    for name in ("_meta", "_themespace", "set_themespace", "bind_meta"):
        assert not hasattr(WorkspaceStructure, name), name


# -- the constants record ---------------------------------------------------------------------


def test_a_run_holds_the_constants_of_its_own_configuration(meta, other_meta):
    a = _make(meta, *PAIRS[0][0])
    b = _make(other_meta, *PAIRS[0][1])
    assert a.ctx.binding.constants == RunConstants.from_metadata(meta)
    assert b.ctx.binding.constants == RunConstants.from_metadata(other_meta)
    assert a.ctx.binding.constants.weakness_exponent != b.ctx.binding.constants.weakness_exponent
    assert a.ctx.binding.meta is a.meta and b.ctx.binding.meta is b.meta
    assert a.ctx.binding.themespace is a.ctx.themespace
    assert b.ctx.binding.themespace is b.ctx.themespace
    assert a.ctx.binding.themespace is not b.ctx.binding.themespace


def test_a_changed_configuration_reaches_the_next_run_and_not_the_running_one(
    meta, other_meta
):
    """A provider is never mutated (an edit swaps the object in the store), and a run
    resolves its constants once from the provider it was given."""
    running = _make(meta, *PAIRS[0][0])
    held = running.ctx.binding.constants
    for _ in range(40):
        running.step_mcat()
    store = {"current": meta}
    store["current"] = other_meta  # the edit
    after = _make(store["current"], *PAIRS[0][1])
    for _ in range(40):
        running.step_mcat()
    assert running.ctx.binding.constants is held
    assert running.ctx.binding.constants.weakness_exponent == meta.get_formula_coeff(
        "weakness_exponent"
    )
    assert after.ctx.binding.constants.weakness_exponent == 0.9


def test_run_constants_are_frozen_and_slotted(meta):
    rc = RunConstants.from_metadata(meta)
    with pytest.raises(dataclasses.FrozenInstanceError):
        rc.weakness_exponent = 2  # type: ignore[misc]
    assert not hasattr(rc, "__dict__")


def test_run_parameter_overrides_reach_the_constants(meta):
    runner = EngineRunner(meta)
    runner.init_mcat(
        "abc", "abd", "xyz", seed=1, memory=EpisodicMemory(),
        parameters={"update_cycle_length": 30},
    )
    assert runner.ctx.binding.meta is runner.meta
    assert runner.ctx.binding.meta.get_param("update_cycle_length") == 30
    assert runner.ctx.binding.constants == RunConstants.from_metadata(runner.meta)


def test_a_context_built_by_hand_binds_its_own_provider(meta):
    runner = _make(meta, *PAIRS[0][0])
    ctx = runner.ctx
    rebuilt = type(ctx)(
        workspace=ctx.workspace, slipnet=ctx.slipnet, coderack=ctx.coderack,
        themespace=ctx.themespace, trace=ctx.trace, memory=ctx.memory,
        temperature=ctx.temperature, commentary=ctx.commentary, rng=ctx.rng, meta=meta,
    )
    assert isinstance(rebuilt.binding, RunBinding)
    assert rebuilt.binding.themespace is ctx.themespace
    assert rebuilt.binding.constants == RunConstants.from_metadata(meta)
