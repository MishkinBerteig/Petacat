"""Consume the expected-range baseline: sample a problem, compare set membership.

``scripts/build_expected_range.py`` produces the baseline; this module is the other
half of the oracle — the cheap check that a change to the engine has not moved the
set of stopping states a problem can reach.  The two must agree exactly on what a
"stopping state" is, so the key built here (``f"{status}:{answer}"``) and the per-run
codelet cap are deliberately duplicated from the build script rather than derived
from it.  The build script is a standalone tool and importing it from the test suite
would couple the suite to its argument parsing and module-level state.

Why this lives in ``tests/support`` rather than inside a test module
-------------------------------------------------------------------
The expected range is the standard verification for the whole of Phase 0.  WP1.1
(incremental coderack eviction) has to show the range is unchanged; WP0.5 has to
show *where* the range moves as staleness increases; WP4.x has to show it survives
concurrency.  Each of those points the same checker at a different engine
configuration, which is what the ``run_one`` seam is for: supply a callable that
executes one run however that work package needs it executed, and every other part
of the comparison — seeds, sampling, novelty, absence — stays fixed.

The two-sided rule
------------------
The set test is one-sided by nature: sampling 100 runs can show a state is
*reachable*, but not that it is *unreachable*.  So the check treats the two
directions differently, and the baseline records what is needed for each.

* A state outside ``expected_range`` is **novel**, not a failure.  The baseline is
  saturated but not exhaustive, and ``f1_over_n`` quantifies exactly how often an
  always-reachable state should first appear here: at ``f1/N = 0.0001`` a 100-run
  check surfaces one roughly 1% of the time, per problem.  Failing on that would
  make the check cry wolf about once every ten cycles.  The plan's instruction is
  to investigate — re-sample that problem deeply and, if the state proves
  old-but-rare, add it to the baseline.

* A state listed in ``absence_check`` that does *not* appear **is** a failure.
  Those are the most-frequent states summing to at least 50% of the baseline
  sample, and they are frequent enough that their absence is decisive rather than
  suggestive: the rarest one across the 13 problems sits at 20% frequency, whose
  absence from 100 runs has probability 1e-10.  Everything rarer is ignored in this
  direction, because at n=100 its absence carries no information.
"""

from __future__ import annotations

import json
import os
from collections import Counter
from contextlib import contextmanager
from dataclasses import dataclass, field
from multiprocessing import Pool
from multiprocessing.pool import Pool as ProcessPool
from typing import Callable, Iterator, Protocol, Sequence

from server.engine.metadata import MetadataProvider
from server.engine.runner import EngineRunner

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SEED_DIR = os.path.join(REPO, "seed_data")
DEFAULT_BASELINE = os.path.join(REPO, "tests", "fixtures", "expected_range.json")

# Must match ``build_expected_range.MAX_STEPS``.  A different cap is a different
# experiment: raising it lets slow runs reach answers they were previously halted
# short of, which shows up as novel states that have nothing to do with the change
# under test.  The baseline records its own value under ``criterion``, and
# ``load_baseline`` asserts the two agree.
MAX_STEPS = 6000

# The baseline was built from seeds 0..runs-1, with the largest problem taking
# 100,000 runs.  A check that replayed those seeds would reproduce the baseline
# sample exactly and could only fail if the engine had changed — which sounds like
# the point, but it means the check tests *determinism under a fixed seed* rather
# than *the reachable set*, and it would flag every legitimate reordering of the
# random stream.  Sampling from a disjoint seed range instead asks the question the
# oracle is for: does this engine still reach the same states, on runs the baseline
# never saw?  One million leaves an order of magnitude of headroom above the
# largest baseline sample, so the ranges cannot collide even if a problem is later
# re-saturated far past 100,000 runs.
CHECK_SEED_OFFSET = 1_000_000


class NovelStoppingState(UserWarning):
    """A stopping state outside the baseline's expected range.

    Raised as a warning rather than an error, per the two-sided rule above.  It is a
    distinct class so that a work package which *expects* the range to move — WP0.5
    deliberately pushes staleness until it does — can filter for it, and so a novel
    state is never lost in a generic warning summary.
    """


class RunOne(Protocol):
    """One run of one problem, reduced to its stopping state.

    ``problem`` is a baseline record (or any mapping with ``initial``, ``modified``
    and ``target``).  The return value is the ``status:answer`` key.

    When the sample runs across a process pool the callable is handed to the worker
    initialiser, so it must be picklable — in practice, a module-level function.
    """

    def __call__(
        self, meta: MetadataProvider, problem: dict, seed: int, max_steps: int
    ) -> str: ...


def default_run_one(
    meta: MetadataProvider, problem: dict, seed: int, max_steps: int
) -> str:
    """Execute one discovery run and return its stopping state.

    Not answering is a stopping state like any other and is recorded as ``halted:``
    or ``gave_up:``.  Gaining or losing the ability to fail on a problem is exactly
    the kind of change the oracle exists to catch, so those must not be filtered out.
    """
    runner = EngineRunner(meta)
    runner.init_mcat(
        problem["initial"],
        problem["modified"],
        problem["target"],
        seed=seed,
    )
    runner.run_mcat(max_steps=max_steps)
    workspace = runner.ctx.workspace
    answer = workspace.answer_string.text if workspace.answer_string else ""
    return f"{runner.status}:{answer}"


# ─────────────────────────────────────────────────────────────────────────────
# The baseline
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Baseline:
    """The committed baseline, read once and addressed by problem name."""

    path: str
    criterion: dict
    totals: dict
    problems: tuple[dict, ...]

    @property
    def names(self) -> list[str]:
        return [record["name"] for record in self.problems]

    def by_name(self, name: str) -> dict:
        for record in self.problems:
            if record["name"] == name:
                return record
        raise KeyError(f"no problem named {name!r} in {self.path}")

    def __len__(self) -> int:
        return len(self.problems)

    def __iter__(self) -> Iterator[dict]:
        return iter(self.problems)


def load_baseline(path: str | None = None) -> Baseline:
    """Load ``tests/fixtures/expected_range.json``.

    The per-run codelet cap is checked rather than adopted: silently sampling at the
    baseline's cap would hide the case where this module and the build script have
    drifted apart, and a mismatched cap invalidates the comparison outright.
    """
    path = path or DEFAULT_BASELINE
    with open(path) as fh:
        payload = json.load(fh)
    criterion = payload.get("criterion", {})
    recorded_cap = criterion.get("max_steps_per_run")
    if recorded_cap is not None and recorded_cap != MAX_STEPS:
        raise ValueError(
            f"{path} was built with max_steps_per_run={recorded_cap}, but this "
            f"checker samples at {MAX_STEPS}. Samples taken at different caps are "
            f"not comparable."
        )
    return Baseline(
        path=path,
        criterion=criterion,
        totals=payload.get("totals", {}),
        problems=tuple(payload["problems"]),
    )


def problem_label(record: dict) -> str:
    """``abc->abd; xyz?`` — how the build script and the plan both write a problem."""
    return f"{record['initial']}->{record['modified']}; {record['target']}?"


# ─────────────────────────────────────────────────────────────────────────────
# Sampling
# ─────────────────────────────────────────────────────────────────────────────

_META: MetadataProvider | None = None
_RUN_ONE: RunOne = default_run_one
_LOCAL_META: MetadataProvider | None = None


def default_workers() -> int:
    """One fewer than the core count, as the build script uses.

    Leaving a core free keeps the machine responsive and, more usefully, keeps the
    measured runs/s stable enough to compare between work packages.
    """
    return max(1, (os.cpu_count() or 4) - 1)


def _init_worker(seed_dir: str, run_one: RunOne) -> None:
    """Load the metadata once per worker rather than once per run.

    ``MetadataProvider.from_seed_data`` costs a couple of milliseconds against a
    ~130 ms run, which is small but not free at 1,300 runs, and it would otherwise
    be paid on every task.
    """
    global _META, _RUN_ONE
    _META = MetadataProvider.from_seed_data(seed_dir)
    _RUN_ONE = run_one


def _worker_task(task: tuple[dict, int, int]) -> str:
    problem, seed, max_steps = task
    assert _META is not None  # set by _init_worker
    return _RUN_ONE(_META, problem, seed, max_steps)


@contextmanager
def worker_pool(
    workers: int | None = None,
    run_one: RunOne | None = None,
    seed_dir: str | None = None,
) -> Iterator[ProcessPool]:
    """A process pool with the metadata already loaded in every worker.

    Worth hoisting out of ``sample_problem`` when several problems are checked in
    one session: starting a pool spawns N interpreters, and paying that once for
    thirteen problems rather than thirteen times is most of the difference between
    the routine check being seconds and being a minute.
    """
    workers = default_workers() if workers is None else workers
    initargs = (seed_dir or SEED_DIR, run_one or default_run_one)
    with Pool(workers, initializer=_init_worker, initargs=initargs) as pool:
        yield pool


def _local_meta(seed_dir: str) -> MetadataProvider:
    global _LOCAL_META
    if _LOCAL_META is None:
        _LOCAL_META = MetadataProvider.from_seed_data(seed_dir)
    return _LOCAL_META


def sample_seeds(n_runs: int, seed_offset: int = CHECK_SEED_OFFSET) -> range:
    """The seeds a check of ``n_runs`` uses — deterministic, and disjoint from the
    baseline's own ``0..runs-1``.  Exposed so a run that surfaces a novel state can
    be reproduced exactly from the seed that produced it."""
    return range(seed_offset, seed_offset + n_runs)


def sample_problem(
    problem: dict,
    n_runs: int,
    seed_offset: int = CHECK_SEED_OFFSET,
    workers: int | None = None,
    max_steps: int = MAX_STEPS,
    run_one: RunOne | None = None,
    pool: ProcessPool | None = None,
    seed_dir: str | None = None,
) -> Counter:
    """Run ``problem`` ``n_runs`` times in discovery mode; count stopping states.

    Frequencies come back because they are useful when reading a failure — how often
    a novel state occurred says a great deal about whether it is old-but-rare or
    newly common — but the comparison in ``check_problem`` is set membership only.

    ``pool`` reuses an existing pool from ``worker_pool``.  The run callable is fixed
    when that pool is created, so passing both is a contradiction and is rejected
    rather than silently resolved.  ``workers=1`` runs in-process, which is the right
    choice for a handful of runs and the only choice for a non-picklable ``run_one``.
    """
    if pool is not None and run_one is not None:
        raise ValueError(
            "run_one is bound when the pool is created; pass it to worker_pool() "
            "instead of to sample_problem()"
        )
    seed_dir = seed_dir or SEED_DIR
    tasks = [(problem, seed, max_steps) for seed in sample_seeds(n_runs, seed_offset)]

    if pool is None and (workers or default_workers()) == 1:
        meta = _local_meta(seed_dir)
        runner = run_one or default_run_one
        return Counter(runner(meta, p, s, m) for p, s, m in tasks)

    # Small chunks: the work is uniform enough that the scheduling overhead is
    # irrelevant next to a ~130 ms run, and a large chunk on a 100-run sample would
    # leave most of the pool idle.
    n_workers = workers or default_workers()
    chunksize = max(1, n_runs // (n_workers * 4))

    if pool is not None:
        return Counter(pool.map(_worker_task, tasks, chunksize=chunksize))
    with worker_pool(n_workers, run_one, seed_dir) as own_pool:
        return Counter(own_pool.map(_worker_task, tasks, chunksize=chunksize))


# ─────────────────────────────────────────────────────────────────────────────
# The comparison
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class CheckResult:
    """One problem's sample, compared against its baseline record."""

    name: str
    label: str
    runs: int
    observed: Counter = field(repr=False)
    #: Observed states absent from ``expected_range``, with their sample counts.
    novel: dict[str, int]
    #: ``absence_check`` states that the sample failed to produce. Failures.
    missing: list[str]
    #: ``absence_check`` states the sample did produce, with their counts.
    present: dict[str, int]
    #: The baseline's f1/N, i.e. the per-check probability of a spurious novel state.
    f1_over_n: float

    @property
    def ok(self) -> bool:
        """Only absence fails a check. Novelty is a prompt to investigate."""
        return not self.missing

    @property
    def novel_alarm_rate(self) -> float:
        """Probability this sample surfaces at least one always-reachable state the
        baseline had not yet seen, from the baseline's own missing-mass estimate.
        Reported alongside a novel state so it can be read as noise or as signal."""
        return 1.0 - (1.0 - self.f1_over_n) ** self.runs

    def describe(self) -> str:
        lines = [
            f"{self.name}  ({self.label})  {self.runs} runs, "
            f"{len(self.observed)} distinct stopping states"
        ]
        if self.missing:
            lines.append(
                "  MISSING — states the baseline says should be common, but which "
                "did not occur:"
            )
            lines.extend(f"    {state}" for state in self.missing)
        if self.present:
            lines.append("  absence-check states present:")
            lines.extend(
                f"    {state}  x{count}" for state, count in sorted(self.present.items())
            )
        if self.novel:
            lines.append(
                f"  NOVEL — outside the baseline's expected range (expected in "
                f"~{self.novel_alarm_rate:.1%} of checks by chance alone):"
            )
            lines.extend(
                f"    {state}  x{count}" for state, count in sorted(self.novel.items())
            )
        return "\n".join(lines)


def check_problem(record: dict, observed: Counter) -> CheckResult:
    """Compare a sample against one baseline record.

    Set membership only: the baseline's own frequencies are never compared against
    the sample's, because reordering codelets moves frequencies around freely without
    changing which states are reachable, and a frequency test would fire on every
    such change while telling us nothing about correctness.
    """
    expected = set(record["expected_range"])
    absence_states = record.get("absence_check", {}).get("states", [])
    runs = sum(observed.values())

    novel = {state: count for state, count in observed.items() if state not in expected}
    missing = [state for state in absence_states if state not in observed]
    present = {state: observed[state] for state in absence_states if state in observed}

    return CheckResult(
        name=record["name"],
        label=problem_label(record),
        runs=runs,
        observed=observed,
        novel=novel,
        missing=missing,
        present=present,
        f1_over_n=record.get("f1_over_n", 0.0),
    )


def check_all(
    baseline: Baseline,
    n_runs: int,
    workers: int | None = None,
    run_one: RunOne | None = None,
    names: Sequence[str] | None = None,
    progress: Callable[[CheckResult], None] | None = None,
) -> list[CheckResult]:
    """Check every problem in the baseline over a single shared pool.

    The pytest entry point parametrises over problems instead, so each shows up as
    its own test; this is for scripts and for interactive use, where one call and one
    pool is easier than driving pytest.
    """
    records = [baseline.by_name(n) for n in names] if names else list(baseline)
    results: list[CheckResult] = []
    with worker_pool(workers, run_one) as pool:
        for record in records:
            observed = sample_problem(record, n_runs, pool=pool)
            result = check_problem(record, observed)
            results.append(result)
            if progress is not None:
                progress(result)
    return results
