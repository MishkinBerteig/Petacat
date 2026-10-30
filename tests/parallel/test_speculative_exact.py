"""The speculative engine must be bit-identical to the stream-serial reference (SSR).

What these defend
-----------------
For every worker count the engine's record of a run equals the SSR's, in everything an
observer can see: the step-by-step sequence of codelet type and id, every structure the sink
was told was built or broken (in order), every Trace event, the answers, the status, the
codelet count, and a fingerprint of the final shared state.  A speculative engine that is
merely *close* is the free-running engine this replaces, so the comparison is exact.

Races are probabilistic, so the quick tests cover the demo problems at a short horizon on
several worker counts, ``chaos`` forces otherwise-valid speculations to abort (exercising the
re-execution and rollback paths on every run), and the ``slow`` sweep runs far more seeds,
full-length runs and 16 workers.  Run them under both interpreters: the GIL build serialises
bytecode, so only ``.venv-ft`` (no GIL) shows the interleavings that matter::

    .venv/bin/python    -m pytest tests/parallel/test_speculative_exact.py
    .venv-ft/bin/python -m pytest tests/parallel/test_speculative_exact.py -m slow
    PETACAT_SPECULATIVE_SWEEP_SEEDS=5 .venv-ft/bin/python -m pytest ... -m slow   # the full sweep
"""

from __future__ import annotations

import json
import os
import sys

import pytest

from server.engine.metadata import MetadataProvider
from server.engine.runner import EngineRunner
from server.parallel.speculative.compare import diff, run_record

SEED_DATA = os.path.join(os.path.dirname(__file__), "..", "..", "seed_data")


@pytest.fixture(scope="module")
def meta():
    return MetadataProvider.from_seed_data(SEED_DATA)


def problems():
    with open(os.path.join(SEED_DATA, "demo_problems.json")) as f:
        demo = json.load(f)
    seen, out = set(), []
    for p in demo:
        key = (p["initial"], p["modified"], p["target"],
               p.get("answer") if p["mode"] == "justification" else None)
        if key not in seen:
            seen.add(key)
            out.append(key)
    return out


PROBLEMS = problems()
#: Discovery and justification, short and long strings, groups, copies.
QUICK = [0, 1, 4, 7, 12, 14, 16, 20, 27]
GIL = getattr(sys, "_is_gil_enabled", lambda: True)()


def check(meta, problem, seed, workers, steps, **options):
    ssr = run_record(meta, problem, seed, "ssr", max_steps=steps)
    spec = run_record(meta, problem, seed, "spec", workers=workers, max_steps=steps,
                      use_qos=False, **options)
    assert diff(ssr, spec) == [], (problem, seed, workers, options)
    return ssr, spec


@pytest.mark.parametrize("workers", [1, 2, 4, 8])
@pytest.mark.parametrize("pi", QUICK)
def test_speculative_equals_ssr(meta, pi, workers):
    check(meta, PROBLEMS[pi], 1, workers, 450)


@pytest.mark.parametrize("pi", [0, 6, 16])
def test_inline_plugin_equals_ssr(meta, pi):
    """No threads: the plugin interpreter, guards, deferred jolts and hooks alone."""
    check(meta, PROBLEMS[pi], 2, 0, 600)


@pytest.mark.parametrize("workers", [2, 6])
@pytest.mark.parametrize("pi", [0, 1, 12, 16])
def test_forced_aborts_reexecute_exactly(meta, pi, workers):
    """Half of all valid speculations are failed on purpose: rollback + live re-execution."""
    ssr, spec = check(meta, PROBLEMS[pi], 3, workers, 450, chaos=0.5)
    assert spec.telemetry["aborted_chaos"] > 0


@pytest.mark.parametrize("workers", [0, 2, 4])
def test_stream_update_cycle_policy_is_exact(meta, workers):
    """WP5's stream-keyed update cycle: the SSR and the engine must use the same policy,
    and then agree bit for bit (whatever the update team's thread count)."""
    pytest.importorskip("server.parallel.update_cycle")
    problem = PROBLEMS[0]
    ssr = run_record(meta, problem, 4, "ssr", max_steps=500, update="stream", update_threads=1)
    spec = run_record(meta, problem, 4, "spec", workers=workers, max_steps=500, use_qos=False,
                      update="stream", update_threads=2)
    assert diff(ssr, spec) == []


def test_ssr_is_deterministic(meta):
    a = run_record(meta, PROBLEMS[0], 5, "ssr", max_steps=500)
    b = run_record(meta, PROBLEMS[0], 5, "ssr", max_steps=500)
    assert diff(a, b) == []
    assert a.steps and a.events


def test_engine_leaves_no_trace_when_closed(meta):
    from server.engine.bridges import Bridge
    from server.engine.slipnet import SlipnetNode

    run_record(meta, PROBLEMS[0], 1, "spec", workers=2, max_steps=120, use_qos=False)
    assert not getattr(Bridge, "_spec_patched", 0)
    runner = EngineRunner(meta)
    runner.init_mcat(*PROBLEMS[0], seed=1)
    from server.parallel.speculative.engine import SpeculativeEngine

    with SpeculativeEngine(runner, 2, use_qos=False) as engine:
        engine.install()
    assert all(type(n) is SlipnetNode for n in runner.ctx.slipnet.nodes.values())
    assert "step_mcat" not in runner.__dict__ and "_execute_codelet" not in runner.__dict__


def test_executors_are_registered():
    from server import parallel

    assert {"stream", "speculative"} <= set(parallel.executor_names())
    assert parallel.get_executor("speculative").__name__ == "SpeculativeExecutor"
    assert parallel.get_executor("stream").__name__ == "StreamSerialExecutor"


def test_executor_runs_a_prepared_runner(meta):
    from server import parallel

    runner = EngineRunner(meta)
    runner.init_mcat(*PROBLEMS[0], seed=7)
    result = parallel.get_executor("speculative")(runner, workers=2, use_qos=False).run(200)
    assert result.codelet_count == 200
    ref = EngineRunner(meta)
    ref.init_mcat(*PROBLEMS[0], seed=7)
    ref_result = parallel.get_executor("stream")(ref).run(200)
    assert [s.codelet_type for s in result.steps] == [s.codelet_type for s in ref_result.steps]


#: Seeds per problem in the slow sweep.  One by default, at 4 and 16 workers, so the default
#: suite pays minutes rather than the full sweep's ~25 (five seeds at 2, 4, 8 and 16 workers,
#: as WP3 ran it): ``PETACAT_SPECULATIVE_SWEEP_SEEDS=5`` restores that.
SWEEP_SEEDS = max(1, int(os.environ.get("PETACAT_SPECULATIVE_SWEEP_SEEDS", "1")))
SWEEP_WORKERS = [2, 4, 8, 16] if SWEEP_SEEDS > 1 else [4, 16]


@pytest.mark.slow
@pytest.mark.parametrize("workers", SWEEP_WORKERS)
@pytest.mark.parametrize("pi", range(len(PROBLEMS)))
def test_sweep_many_seeds(meta, pi, workers):
    for seed in range(11, 11 + SWEEP_SEEDS):
        check(meta, PROBLEMS[pi], seed, workers, 2500)


@pytest.mark.slow
@pytest.mark.parametrize("pi", [0, 1, 2, 7, 12, 14])
def test_full_length_runs(meta, pi):
    """Runs to their natural end (an answer, or the generous step cap), 8 workers."""
    ssr, spec = check(meta, PROBLEMS[pi], 21, 8, 12000)
    assert ssr.codelet_count == spec.codelet_count
