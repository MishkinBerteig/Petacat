"""The routine expected-range check — Phase 0's regression oracle in test form.

``tests/fixtures/expected_range.json`` records, for each of the 13 distinct analogy
problems in the demo catalogue, the set of stopping states it can reach.  That set
was established by sampling each problem to Good-Turing saturation, 410,000 runs in
total.  This test spends ~100 runs per problem asking whether the engine still
reaches the same set.

Set membership is what the oracle compares, and the reason is that it is the
invariant that survives what Phase 0 does to the engine.  Reordering codelets — a
different eviction rule, a different random stream, concurrent execution — changes
which state a given seed produces and how often each occurs.  It should not change
which states are *reachable*.  So a seeded-run test would fail on every legitimate
change and a frequency test would fail on most of them, while neither would be able
to say whether anything had actually broken.

The check is deliberately asymmetric, and the two halves are separate outcomes:

* A **missing p50 state is a regression** and fails the test.  The p50 set is the
  smallest group of most-frequent states whose combined frequency in the baseline
  reaches 50%, taken from the baseline's own recorded distribution.  Those states are
  frequent enough that their absence from 100 runs is decisive.
* A **novel state** — one outside the range the fixture accepts — is surfaced **for
  the user to adjudicate**.  They decide whether it belongs in the set or is a
  defect; the test never widens the fixture.  The report names the problem, the
  state, the numeric backend, the sample size and the baseline's own false-alarm
  rate, which is what the decision needs.  Re-sample first with
  ``scripts/build_expected_range.py --problem NAME --force``.

Both halves apply on every configuration.  A backend's arithmetic explains how a run
diverged; whether the state it reached belongs in the reachable set is the user's
question either way.

Environment overrides, for running the same check harder or elsewhere on demand::

    PETACAT_RANGE_RUNS=1000 python3 -m pytest tests/module/test_expected_range.py
    PETACAT_RANGE_WORKERS=4 python3 -m pytest tests/module/test_expected_range.py
    PETACAT_RANGE_GPU=0 python3 -m pytest tests/module/test_expected_range.py

The full check is marked ``slow`` so it can be deselected with ``-m "not slow"``, but
it is on by default: the plan treats it as the standard verification for every
subsequent work package, and a guard that has to be remembered is not a guard.

Cost, measured: 1,300 runs in 61–74 s across 11 workers, or ~18–21 runs/s.  The plan
quotes 44–55 runs/s and "under a minute", which is the throughput of the problems
that dominated the *baseline build* — ``fig5.7``, ``run3`` and ``run4`` between them
account for 175,000 of its 410,000 runs and each manages ~45–48 runs/s.  This check
runs 100 of every problem, so it is dominated instead by the slow ones: ``fig5.4-top``
and ``misc3`` manage 5–6 runs/s and together take half the wall-clock, because their
runs mostly exhaust the 6,000-codelet cap rather than reaching an answer early.

The GPU check costs 316 s for the same 1,300 runs across 11 workers, measured over
three consecutive passes on an M2 Max — 4.1× the vectorised-CPU cost.  That ratio is
the substrate's, not the pool's: a Metal dispatch costs ~0.2 ms whether it carries
200 edges or 340,000, and the 59-node Slipnet's numeric work is far below that, so
every update cycle pays a dispatch it cannot fill.  ``PETACAT_RANGE_GPU_WORKERS``
sizes the GPU pool independently of the CPU one, and ``PETACAT_RANGE_GPU_RUNS`` sets
its sample depth.
"""

import os
import warnings
from collections import Counter

import pytest

from tests.support.expected_range import (
    DEFAULT_WORKER_BACKENDS,
    GPU_BACKENDS,
    NovelStoppingState,
    SampleStalled,
    SampleWorkerLost,
    check_problem,
    default_workers,
    first_available_backend,
    gpu_is_available,
    load_baseline,
    p50_states,
    resolved_worker_backend,
    sample_problem,
    sample_seeds,
    sample_timeout,
    worker_backends,
    worker_pool,
)


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    return int(raw) if raw else default


#: 100 runs per problem, the sample size the baseline's p50 absence probabilities
#: were computed for. Raising it makes absence evidence stronger and novelty more
#: likely; both are proportionate, so the defaults do not need to move together.
RUNS_PER_PROBLEM = _env_int("PETACAT_RANGE_RUNS", 100)
WORKERS = _env_int("PETACAT_RANGE_WORKERS", default_workers())

#: The GPU check runs with the suite: the reachable set is the standard every cognition
#: change is held to, and it is held on both numeric roles.  ``PETACAT_RANGE_GPU=0``
#: narrows a run to the CPU role.
GPU_REQUESTED = os.environ.get("PETACAT_RANGE_GPU", "1") != "0"
GPU_RUNS_PER_PROBLEM = _env_int("PETACAT_RANGE_GPU_RUNS", RUNS_PER_PROBLEM)
GPU_WORKERS = _env_int("PETACAT_RANGE_GPU_WORKERS", WORKERS)

#: The name each sample is filed under, so a difference names its configuration.
BACKEND = resolved_worker_backend()
GPU_BACKEND = GPU_BACKENDS[0]

# Read at import time so the 13 problems become 13 parametrised cases, each named
# after its demo. A failure then points at one problem rather than at "the check".
BASELINE = load_baseline()
PROBLEM_NAMES = BASELINE.names


def _report(result, record_property) -> None:
    """File a novel state for the user's decision, and fail on a missing p50 state.

    The two outcomes go to different places on purpose.  A regression is an
    assertion, so it stops the suite.  An adjudication is a warning and a recorded
    property, so it survives into the report the user reads without pretending the
    engine is broken.
    """
    if result.novel:
        for state, count in sorted(result.novel.items()):
            record_property(
                "adjudicate_stopping_state",
                f"{result.name} [{result.backend}]: {state} (x{count} of {result.runs})",
            )
        warnings.warn(
            result.adjudication()
            + f"\n  Seeds used here: {sample_seeds(result.runs)}.",
            NovelStoppingState,
            # Default stacklevel: the warning summary should point at this line in
            # this file, not at pytest's frame for calling the test.
        )
    assert result.ok, result.regression()


@pytest.fixture(scope="module")
def pool():
    """One pool for all 13 problems.

    Starting a pool spawns eleven interpreters and loads the seed data in each. Paid
    once, that is noise against 1,300 runs; paid per problem it would be most of the
    check's wall-clock.
    """
    with worker_pool(workers=WORKERS) as p:
        yield p


@pytest.mark.slow
@pytest.mark.parametrize("name", PROBLEM_NAMES)
def test_stopping_states_stay_within_the_expected_range(name, pool, record_property):
    record = BASELINE.by_name(name)
    observed = sample_problem(record, RUNS_PER_PROBLEM, pool=pool)
    _report(check_problem(record, observed, backend=BACKEND), record_property)


# ─────────────────────────────────────────────────────────────────────────────
# The same check, on the Metal GPU
#
# The engine's default policy puts the numeric substrate on the GPU at every Slipnet
# size, so the GPU is what a Petacat run uses.  Its arithmetic is float32 against a
# float64 reference, which forks the random stream and sends a given seed to a
# different answer — the reason the oracle compares sets rather than seeded runs, and
# the reason the set is the thing worth asking the GPU about.
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def gpu_pool():
    """A pool whose workers run the numeric substrate on Metal.

    ``PETACAT_RANGE_GPU=1`` asks for it, and MLX has to be installed and its Metal
    probe has to succeed.  Both conditions are checked before the pool is built so
    that an absent GPU skips rather than fails, which is how every other
    backend-specific test in the suite behaves.
    """
    if not GPU_REQUESTED:
        pytest.skip("PETACAT_RANGE_GPU=0 narrows this run to the CPU role")
    if not gpu_is_available():
        pytest.skip(f"the {GPU_BACKEND} backend is not available on this machine")
    with worker_pool(workers=GPU_WORKERS, backends=GPU_BACKENDS) as p:
        yield p


@pytest.mark.slow
@pytest.mark.parametrize("name", PROBLEM_NAMES)
def test_the_gpu_reaches_the_same_expected_range(name, gpu_pool, record_property):
    record = BASELINE.by_name(name)
    observed = sample_problem(record, GPU_RUNS_PER_PROBLEM, pool=gpu_pool)
    _report(check_problem(record, observed, backend=GPU_BACKEND), record_property)


# ─────────────────────────────────────────────────────────────────────────────
# The checker's own logic, on synthetic samples
#
# The check above cannot exercise its own failure path — it passes precisely when
# nothing is missing — so the comparison rule is tested directly. These run in
# milliseconds and are not marked slow.
# ─────────────────────────────────────────────────────────────────────────────

SYNTHETIC = {
    "name": "synthetic",
    "initial": "abc",
    "modified": "abd",
    "target": "xyz",
    "runs": 10000,
    "expected_range": ["answer_found:xyd", "answer_found:wyz", "gave_up:"],
    "f1_over_n": 0.0001,
    "counts": {"answer_found:xyd": 6500, "gave_up:": 3499, "answer_found:wyz": 1},
    "absence_check": {
        "states": ["answer_found:xyd"],
        "cumulative_frequency": 0.65,
    },
}

#: The same problem with the p50 set left for ``p50_states`` to compute from
#: ``counts``. The two must name the same states.
SYNTHETIC_WITHOUT_RECORDED_P50 = {
    k: v for k, v in SYNTHETIC.items() if k != "absence_check"
}


def test_a_sample_inside_the_expected_range_passes():
    result = check_problem(SYNTHETIC, Counter({"answer_found:xyd": 65, "gave_up:": 35}))
    assert result.ok
    assert result.novel == {}
    assert result.missing == []
    assert result.present == {"answer_found:xyd": 65}


def test_the_p50_set_comes_from_the_recorded_distribution():
    """``counts`` carries the baseline's frequencies, so the p50 set is derivable from
    the record even where the build script did not name it. ``answer_found:xyd`` is
    65% of 10,000 runs and reaches the halfway mark on its own."""
    assert p50_states(SYNTHETIC_WITHOUT_RECORDED_P50) == ["answer_found:xyd"]
    assert p50_states(SYNTHETIC) == p50_states(SYNTHETIC_WITHOUT_RECORDED_P50)


def test_a_missing_p50_state_is_a_regression_and_fails():
    """``answer_found:xyd`` is 65% of the baseline; a healthy engine reaches it
    routinely, so its absence from 100 runs is a defect rather than sampling noise."""
    result = check_problem(
        SYNTHETIC, Counter({"answer_found:wyz": 60, "gave_up:": 40}), backend="numpy"
    )
    assert result.missing == ["answer_found:xyd"]
    assert not result.ok
    assert "REGRESSION" in result.regression()
    assert "answer_found:xyd" in result.regression()
    assert "numpy" in result.regression()


def test_a_missing_p50_state_is_a_regression_without_a_recorded_p50_set():
    """The rule holds on a record whose p50 set is computed rather than read."""
    result = check_problem(
        SYNTHETIC_WITHOUT_RECORDED_P50, Counter({"gave_up:": 100})
    )
    assert result.missing == ["answer_found:xyd"]
    assert not result.ok


def test_a_novel_state_is_surfaced_for_adjudication_rather_than_failed():
    """The user decides whether a state outside the fixture belongs in the set. The
    check reports it and passes; nothing here widens the fixture."""
    observed = Counter({"answer_found:xyd": 65, "gave_up:": 34, "answer_found:xyz": 1})
    result = check_problem(SYNTHETIC, observed, backend="mlx")
    assert result.novel == {"answer_found:xyz": 1}
    assert result.ok, "a novel state is a question for the user, not a failure"


def test_the_adjudication_report_carries_what_the_decision_needs():
    """Which problem, which state, which backend, how many samples, and how likely a
    genuinely-novel state is at this sample size."""
    observed = Counter({"answer_found:xyd": 99, "answer_found:xyz": 1})
    report = check_problem(SYNTHETIC, observed, backend="mlx").adjudication()
    assert "ADJUDICATE" in report
    assert "synthetic" in report
    assert "abc->abd; xyz?" in report
    assert "answer_found:xyz" in report
    assert "mlx" in report
    assert "100 runs" in report
    assert "expected_range.json" in report


def test_a_state_the_user_has_admitted_is_inside_the_range():
    """An adjudication takes effect as soon as it is written into the fixture, without
    waiting for the baseline to be rebuilt from its saturation counts."""
    record = {**SYNTHETIC, "admitted_states": {"answer_found:xyz": "seen on the GPU"}}
    result = check_problem(record, Counter({"answer_found:xyd": 99, "answer_found:xyz": 1}))
    assert result.novel == {}
    assert result.ok


def test_a_rare_baseline_state_missing_from_the_sample_is_ignored():
    """Absence only counts for the p50 set. ``answer_found:wyz`` is in the expected
    range but is 1 run in 10,000, so a sample without it says nothing — which is why
    the baseline records the frequent states separately."""
    result = check_problem(SYNTHETIC, Counter({"answer_found:xyd": 70, "gave_up:": 30}))
    assert result.ok
    assert result.missing == []


def test_the_novel_alarm_rate_follows_the_baselines_missing_mass():
    """The number quoted in the adjudication report is derived, not guessed: one minus
    the chance that none of ``runs`` draws lands on an unseen state."""
    result = check_problem(SYNTHETIC, Counter({"answer_found:xyd": 100}))
    assert result.runs == 100
    assert result.novel_alarm_rate == pytest.approx(1 - 0.9999**100, rel=1e-9)


# ─────────────────────────────────────────────────────────────────────────────
# The sampling seam
# ─────────────────────────────────────────────────────────────────────────────


def _echo_seed(meta, problem, seed, max_steps):
    """A stand-in for a real run: reports the seed it was given as the answer."""
    return f"answer_found:{seed}"


def _never_finishes(meta, problem, seed, max_steps):
    """A stand-in for a run that stops making progress."""
    import time

    time.sleep(3600)
    return "answer_found:never"


def _kills_its_worker(meta, problem, seed, max_steps):
    """A stand-in for a run whose process disappears while it holds the run.

    ``os._exit`` skips every cleanup path, which is what a worker killed by the
    operating system or lost inside a native library looks like to the pool.
    """
    import os

    if seed % 4 == 3:
        os._exit(70)
    return "answer_found:survived"


def test_the_check_samples_seeds_the_baseline_never_used():
    """If the check replayed seeds 0..N-1 it would be replaying the very runs the
    baseline is made of, and would agree with it by construction. The largest baseline
    sample is 100,000 runs; the check starts at 1,000,000."""
    observed = sample_problem(SYNTHETIC, 5, workers=1, run_one=_echo_seed)
    seeds = sorted(int(state.split(":")[1]) for state in observed)
    assert seeds == [1_000_000, 1_000_001, 1_000_002, 1_000_003, 1_000_004]
    assert min(seeds) > max(r["runs"] for r in BASELINE)


# ─────────────────────────────────────────────────────────────────────────────
# The sampling budget
#
# The oracle is the gate every cognition change is measured against, and a stalled
# check reads exactly like a slow one. A bounded wait is what tells them apart.
# ─────────────────────────────────────────────────────────────────────────────


def test_a_stalled_sample_announces_itself_instead_of_waiting():
    """The pool is left holding work that never completes; the budget expires and the
    sample raises, naming the problem and what to do about it."""
    with pytest.raises(SampleStalled) as excinfo:
        sample_problem(
            SYNTHETIC, 4, workers=2, run_one=_never_finishes, timeout=3.0
        )
    assert "synthetic" in str(excinfo.value)
    assert "PETACAT_RANGE_TIMEOUT" in str(excinfo.value)


def test_a_lost_worker_is_named_within_a_second():
    """A worker that exits mid-run takes its task with it: ``multiprocessing.Pool``
    replaces the process and does not re-send the work, leaving a result that no
    process is going to produce. Watching the worker identities turns that into an
    immediate, named failure, inside a second and well before the budget expires."""
    with pytest.raises(SampleWorkerLost) as excinfo:
        sample_problem(
            SYNTHETIC, 8, workers=2, run_one=_kills_its_worker, timeout=120.0
        )
    message = str(excinfo.value)
    assert "lost worker process" in message
    assert "synthetic" in message


def test_the_budget_scales_with_the_sample_size():
    """Raising PETACAT_RANGE_RUNS raises the allowance with it, so a deeper re-sample
    is not held to the budget a shallow one earned."""
    assert sample_timeout(10_000) > sample_timeout(1_000) > sample_timeout(100)
    assert sample_timeout(1) == pytest.approx(600.0)


def test_the_budget_can_be_lifted_entirely(monkeypatch):
    monkeypatch.setenv("PETACAT_RANGE_TIMEOUT", "0")
    assert sample_timeout(100) is None
    monkeypatch.setenv("PETACAT_RANGE_TIMEOUT", "42")
    assert sample_timeout(100) == pytest.approx(42.0)


# ─────────────────────────────────────────────────────────────────────────────
# Which backend the workers take
# ─────────────────────────────────────────────────────────────────────────────


def test_the_workers_take_the_first_installed_candidate():
    """The candidate list is tried in order, so the check runs under an interpreter
    that has NumPy and under one that has only the reference loops."""
    assert first_available_backend(("definitely-not-a-backend", "python")) == "python"
    assert first_available_backend(DEFAULT_WORKER_BACKENDS) in DEFAULT_WORKER_BACKENDS


def test_asking_for_the_gpu_overrides_the_default_candidates():
    assert worker_backends(GPU_BACKENDS) == GPU_BACKENDS
    assert resolved_worker_backend(GPU_BACKENDS) == GPU_BACKENDS[0]


def test_the_ambient_policy_is_reachable(monkeypatch):
    """PETACAT_ORACLE_ALLOW_GPU=1 leaves the worker to resolve the backend the way
    every other Petacat process does."""
    monkeypatch.setenv("PETACAT_ORACLE_ALLOW_GPU", "1")
    assert worker_backends() is None
    assert resolved_worker_backend() == "ambient policy"


def test_a_pool_and_a_run_callable_together_are_rejected():
    """The callable is bound when the pool is created, so passing both would silently
    ignore one of them."""
    with pytest.raises(ValueError, match="bound when the pool is created"):
        sample_problem(SYNTHETIC, 1, pool=object(), run_one=_echo_seed)
