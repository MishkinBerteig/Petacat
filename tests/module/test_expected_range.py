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

The check is deliberately asymmetric, and the two halves are separate assertions:

* **Missing** an ``absence_check`` state fails the test.  Those states are frequent
  enough in the baseline that their absence from 100 runs is decisive.
* **Novel** states — outside the recorded range — warn rather than fail, because the
  baseline is saturated but not exhaustive and ``f1/N`` says a spurious one turns up
  in about 1% of per-problem checks.  The warning names the problem and the state so
  it is investigated rather than swallowed: re-sample that problem deeply with
  ``scripts/build_expected_range.py --problem NAME --force`` and, if the state proves
  old-but-rare, it belongs in the baseline.

Environment overrides, for running the same check harder on demand::

    PETACAT_RANGE_RUNS=1000 python3 -m pytest tests/module/test_expected_range.py
    PETACAT_RANGE_WORKERS=4 python3 -m pytest tests/module/test_expected_range.py

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
"""

import os
import warnings
from collections import Counter

import pytest

from tests.support.expected_range import (
    NovelStoppingState,
    check_problem,
    default_workers,
    load_baseline,
    problem_label,
    sample_problem,
    sample_seeds,
    worker_pool,
)


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    return int(raw) if raw else default


#: 100 runs per problem, the sample size the baseline's absence-check probabilities
#: were computed for. Raising it makes absence evidence stronger and novelty more
#: likely; both are proportionate, so the defaults do not need to move together.
RUNS_PER_PROBLEM = _env_int("PETACAT_RANGE_RUNS", 100)
WORKERS = _env_int("PETACAT_RANGE_WORKERS", default_workers())

# Read at import time so the 13 problems become 13 parametrised cases, each named
# after its demo. A failure then points at one problem rather than at "the check".
BASELINE = load_baseline()
PROBLEM_NAMES = BASELINE.names


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
    result = check_problem(record, observed)

    for state, count in sorted(result.novel.items()):
        record_property("novel_stopping_state", f"{name}: {state} (x{count})")
        warnings.warn(
            f"{name} ({problem_label(record)}) reached {state!r} {count} time(s) in "
            f"{result.runs} runs; it is not in the baseline's {len(record['expected_range'])} "
            f"recorded states. A state this check has never seen appears by chance in "
            f"~{result.novel_alarm_rate:.1%} of checks of this problem, so this needs "
            f"investigating rather than assuming either way. Re-sample with "
            f"scripts/build_expected_range.py --problem {name} --force; seeds used "
            f"here were {sample_seeds(RUNS_PER_PROBLEM)}.",
            NovelStoppingState,
            # Default stacklevel: the warning summary should point at this line in
            # this file, not at pytest's frame for calling the test.
        )

    assert result.ok, result.describe()


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
    "expected_range": ["answer_found:xyd", "answer_found:wyz", "gave_up:"],
    "f1_over_n": 0.0001,
    "absence_check": {
        "states": ["answer_found:xyd"],
        "cumulative_frequency": 0.65,
    },
}


def test_a_sample_inside_the_expected_range_passes():
    result = check_problem(SYNTHETIC, Counter({"answer_found:xyd": 65, "gave_up:": 35}))
    assert result.ok
    assert result.novel == {}
    assert result.missing == []
    assert result.present == {"answer_found:xyd": 65}


def test_a_state_outside_the_expected_range_is_novel_but_not_a_failure():
    """Novelty is reported, never fatal: at f1/N = 0.0001 roughly one check in a
    hundred surfaces an always-reachable state the baseline had not yet seen."""
    observed = Counter({"answer_found:xyd": 65, "gave_up:": 34, "answer_found:xyz": 1})
    result = check_problem(SYNTHETIC, observed)
    assert result.novel == {"answer_found:xyz": 1}
    assert result.ok, "a novel state must not fail the check"
    assert "NOVEL" in result.describe()


def test_a_missing_absence_check_state_is_a_failure():
    """The other side of the rule. ``answer_found:xyd`` is 65% of the baseline; its
    absence from 100 runs would be evidence, not noise."""
    result = check_problem(SYNTHETIC, Counter({"answer_found:wyz": 60, "gave_up:": 40}))
    assert result.missing == ["answer_found:xyd"]
    assert not result.ok
    assert "MISSING" in result.describe()
    assert "answer_found:xyd" in result.describe()


def test_a_rare_baseline_state_missing_from_the_sample_is_ignored():
    """Absence only counts for the states the baseline nominated. ``answer_found:wyz``
    is in the expected range but not in the absence check, so a sample without it says
    nothing — which is the whole reason the build script records the two separately."""
    result = check_problem(SYNTHETIC, Counter({"answer_found:xyd": 70, "gave_up:": 30}))
    assert result.ok
    assert result.missing == []


def test_the_novel_alarm_rate_follows_the_baselines_missing_mass():
    """The number quoted in the warning is derived, not guessed: one minus the chance
    that none of ``runs`` draws lands on an unseen state."""
    result = check_problem(SYNTHETIC, Counter({"answer_found:xyd": 100}))
    assert result.runs == 100
    assert result.novel_alarm_rate == pytest.approx(1 - 0.9999**100, rel=1e-9)


# ─────────────────────────────────────────────────────────────────────────────
# The sampling seam
# ─────────────────────────────────────────────────────────────────────────────


def _echo_seed(meta, problem, seed, max_steps):
    """A stand-in for a real run: reports the seed it was given as the answer."""
    return f"answer_found:{seed}"


def test_the_check_samples_seeds_the_baseline_never_used():
    """If the check replayed seeds 0..N-1 it would be replaying the very runs the
    baseline is made of, and would agree with it by construction. The largest baseline
    sample is 100,000 runs; the check starts at 1,000,000."""
    observed = sample_problem(SYNTHETIC, 5, workers=1, run_one=_echo_seed)
    seeds = sorted(int(state.split(":")[1]) for state in observed)
    assert seeds == [1_000_000, 1_000_001, 1_000_002, 1_000_003, 1_000_004]
    assert min(seeds) > max(r["runs"] for r in BASELINE)


def test_a_pool_and_a_run_callable_together_are_rejected():
    """The callable is bound when the pool is created, so passing both would silently
    ignore one of them."""
    with pytest.raises(ValueError, match="bound when the pool is created"):
        sample_problem(SYNTHETIC, 1, pool=object(), run_one=_echo_seed)
