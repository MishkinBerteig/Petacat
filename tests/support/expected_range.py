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

* A **missing p50 state is a regression** and fails the check.  The p50 set is the
  smallest group of most-frequent states whose combined frequency in the baseline
  sample reaches 50% — ``p50_states`` reads it from ``absence_check.states``, and
  computes it from the recorded ``counts`` distribution by the same rule where that
  key is absent.  Those states are frequent enough that their absence is decisive
  rather than suggestive: the rarest one across the 13 problems sits at 20%
  frequency, whose absence from 100 runs has probability 1e-10.  Everything rarer is
  ignored in this direction, because at n=100 its absence carries no information.

* A state outside the baseline's accepted range is **novel**, and is reported for
  the user to adjudicate.  They decide whether it belongs in the set or is a defect;
  nothing here widens the fixture.  ``f1_over_n`` quantifies how often an
  always-reachable state should first appear in a sample this size: at
  ``f1/N = 0.0001`` a 100-run check surfaces one roughly 1% of the time, per
  problem.  That number goes into the report as context for the decision, and the
  report also names the numeric backend the sample ran on, because a difference
  belongs to a configuration as much as to a problem.

Every difference is reported the same way whatever produced it — CPU or GPU,
float64 or float32, serial or free-running.  A backend's arithmetic explains *how*
a run diverged; whether the state it reached belongs in the reachable set is a
separate question and is the user's to answer.

The numeric backend the workers run on
--------------------------------------
Each pool worker pins a backend before its first engine object exists, from a
candidate list taken in order — ``DEFAULT_WORKER_BACKENDS`` is vectorised float64
where NumPy is installed and the reference loops where it is not, so the routine
check computes in the reference's precision under either interpreter the suite runs
on.  ``worker_pool(backends=("mlx",))`` puts the sample on Metal instead, which is
where the engine's default policy puts a Petacat run, and
``resolved_worker_backend`` names the result so every ``CheckResult`` says which
configuration produced it.
"""

from __future__ import annotations

import importlib.util
import json
import os
import time
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


#: Set to ``1`` to let pool workers resolve the numeric backend from the ambient
#: policy, which puts them on the GPU at every Slipnet size.
ENV_ALLOW_GPU = "PETACAT_ORACLE_ALLOW_GPU"

#: Comma-separated candidate backends for the pool's workers, most-preferred first.
ENV_WORKER_BACKENDS = "PETACAT_NUMERIC_BACKEND_WORKERS"

#: What the pool's workers run on by default: vectorised CPU where NumPy is
#: installed, the reference loops where it is not.
#:
#: A *list* rather than a name, because the suite runs under two interpreters with
#: different packages installed — ``.venv`` has NumPy and MLX, ``.venv-ft`` has
#: neither — and the check wants the reference's float64 arithmetic under both.
#: Taking the first candidate that is present keeps the rule the rest of the suite
#: follows: a test that wants a specific backend skips when it is absent, and a test
#: that wants *a* backend takes what is there.
DEFAULT_WORKER_BACKENDS: tuple[str, ...] = ("numpy", "python")

#: The module each backend needs before ``get_backend`` will hand it over.
#: ``python`` is the reference implementation and needs nothing.
_BACKEND_REQUIREMENT: dict[str, str | None] = {
    "python": None,
    "numpy": "numpy",
    "mlx": "mlx.core",
    "mlx-cpu": "mlx.core",
}


def first_available_backend(candidates: Sequence[str]) -> str:
    """The first candidate whose dependency is importable.

    ``importlib.util.find_spec`` rather than an import, because this runs in a pool
    worker before the first engine object exists and the answer must not itself
    load MLX: locating a module is a filesystem question, importing one initialises
    whatever the module initialises.  Falls back to ``python``, which is
    unconditional.
    """
    for name in candidates:
        requirement = _BACKEND_REQUIREMENT.get(name, name)
        if requirement is None or importlib.util.find_spec(requirement) is not None:
            return name
    return "python"


def worker_backends(requested: Sequence[str] | None = None) -> tuple[str, ...] | None:
    """Candidate backends for a pool worker, most-preferred first.

    ``None`` — from ``PETACAT_ORACLE_ALLOW_GPU=1`` — means the worker resolves the
    backend from the ambient policy like any other process, GPU included.
    """
    if requested is not None:
        return tuple(requested)
    if os.environ.get(ENV_ALLOW_GPU) == "1":
        return None
    raw = os.environ.get(ENV_WORKER_BACKENDS)
    if raw:
        return tuple(name.strip() for name in raw.split(",") if name.strip())
    return DEFAULT_WORKER_BACKENDS


#: What the GPU check pins its workers to.  A one-element candidate list, because
#: the point of that check is Metal: falling back to a CPU backend would answer a
#: different question under the same test name.
GPU_BACKENDS: tuple[str, ...] = ("mlx",)

_GPU_AVAILABLE: bool | None = None


def _probe_gpu() -> bool:
    """Run in a throwaway subprocess by ``gpu_is_available``."""
    from server.engine.numeric.backend import available_backends

    return GPU_BACKENDS[0] in available_backends()


def gpu_is_available() -> bool:
    """Whether the Metal backend can be built and used in a worker.

    Answered in a throwaway subprocess, for two reasons.  MLX being importable is
    not the same as Metal being usable, and the registry settles that by evaluating
    one small kernel on the GPU stream — which initialises Metal in whatever process
    asks.  Keeping that out of the process that goes on to start the sampling pool
    means the parent stays a plain Python interpreter for the whole check.
    """
    global _GPU_AVAILABLE
    if _GPU_AVAILABLE is None:
        if importlib.util.find_spec("mlx.core") is None:
            _GPU_AVAILABLE = False
        else:
            with Pool(1) as probe:
                _GPU_AVAILABLE = bool(probe.apply(_probe_gpu))
    return _GPU_AVAILABLE


def resolved_worker_backend(backends: Sequence[str] | None = None) -> str:
    """The backend name a pool worker will pin, for the record.

    Answered in the parent, which is exact because ``spawn`` starts each worker from
    ``sys.executable`` and therefore from the same installed packages.  A sample
    carries this name so that a difference from the baseline names the configuration
    that produced it.  ``ambient policy`` is what an unpinned worker follows:
    ``select_backend`` chooses per Slipnet size, which is the GPU wherever MLX runs.
    """
    candidates = worker_backends(backends)
    if candidates is None:
        return "ambient policy"
    return first_available_backend(candidates)


def _init_worker(
    seed_dir: str, run_one: RunOne, backends: tuple[str, ...] | None
) -> None:
    """Load the metadata once per worker rather than once per run.

    ``MetadataProvider.from_seed_data`` costs a couple of milliseconds against a
    ~130 ms run, which is small but not free at 1,300 runs, and it would otherwise
    be paid on every task.

    The backend is pinned here, before the first engine object exists, so that every
    run in the worker resolves the same way.  ``backends=None`` leaves the ambient
    policy alone.
    """
    global _META, _RUN_ONE
    if backends:
        os.environ["PETACAT_NUMERIC_BACKEND"] = first_available_backend(backends)
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
    backends: Sequence[str] | None = None,
) -> Iterator[ProcessPool]:
    """A process pool with the metadata already loaded in every worker.

    Worth hoisting out of ``sample_problem`` when several problems are checked in
    one session: starting a pool spawns N interpreters, and paying that once for
    thirteen problems rather than thirteen times is most of the difference between
    the routine check being seconds and being a minute.

    ``backends`` names the candidate numeric backends for the workers, most
    preferred first; the default comes from ``worker_backends()``.
    """
    workers = default_workers() if workers is None else workers
    initargs = (
        seed_dir or SEED_DIR,
        run_one or default_run_one,
        worker_backends(backends),
    )
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


#: Seconds a single problem's sample may take before it is declared stalled, as a
#: multiple of the run count.  Measured: the slowest problem in the baseline,
#: ``fig5.4-top``, takes 10 s per 100 runs on vectorised CPU across 11 workers and
#: 72 s per 100 runs on Metal, because its runs mostly exhaust the 6,000-codelet cap.
#: Six seconds per run is eight times the slowest of those, which leaves room for a
#: loaded machine and still turns a stall into a failure the same afternoon.
SECONDS_PER_RUN_CEILING = 6.0

#: Floor under the derived budget, so a small sample still gets a usable allowance.
MIN_SAMPLE_TIMEOUT = 600.0

#: Seconds per problem sample, overriding the derived budget. ``0`` waits forever.
ENV_SAMPLE_TIMEOUT = "PETACAT_RANGE_TIMEOUT"

#: ``sample_problem(timeout=...)`` default: derive the budget from the run count.
#: A distinct value rather than ``None``, because ``None`` means "wait forever" and
#: both need to be askable for.
DERIVE_TIMEOUT = -1.0


#: How often the wait on the pool looks up to check that its workers are all still
#: the ones it started with.  A second is far below any real sample's duration and
#: far above the cost of reading a list of process handles.
WORKER_POLL_SECONDS = 1.0


class SampleStalled(RuntimeError):
    """A problem's sample did not finish inside its budget.

    Distinct from a comparison failure, because it says nothing about the reachable
    set: it says the sampling itself stopped making progress.  Raising it is what
    keeps a stalled check from being indistinguishable from a slow one.
    """


class SampleWorkerLost(SampleStalled):
    """A pool worker holding a run disappeared, so its result can never arrive.

    ``multiprocessing.Pool`` replaces a worker that exits and does not re-send the
    task that worker was executing, so ``map`` waits on a result that no process is
    going to produce.  The signature is precise and worth naming, because it is what
    a hung oracle looks like from the outside: every worker at 0% CPU parked on the
    task queue, ``_handle_tasks`` with nothing left to send, ``_handle_results``
    parked in ``recv``, and the calling thread waiting on a result event — for as
    long as the machine stays up.

    Watching the worker identities turns that into an immediate, named failure.  A
    changed set of process ids is unambiguous: a Pool creates its workers once and
    replaces one only when it has lost one.
    """


def sample_timeout(n_runs: int) -> float | None:
    """The budget for one problem's sample, in seconds. ``None`` waits forever.

    Derived from the run count so that raising ``PETACAT_RANGE_RUNS`` raises the
    allowance with it, and floored so that a short sample is not held to a budget
    smaller than pool startup.
    """
    raw = os.environ.get(ENV_SAMPLE_TIMEOUT)
    if raw:
        seconds = float(raw)
        return seconds if seconds > 0 else None
    return max(MIN_SAMPLE_TIMEOUT, SECONDS_PER_RUN_CEILING * n_runs)


def _worker_pids(pool: ProcessPool) -> list[int]:
    """The pool's current worker process ids, in a stable order."""
    return sorted(proc.pid for proc in getattr(pool, "_pool", []))


def _map_within_budget(
    pool: ProcessPool,
    tasks: list[tuple[dict, int, int]],
    chunksize: int,
    timeout: float | None,
    label: str,
) -> Counter:
    """``pool.map`` that answers, whatever happens to the pool.

    Two ways a sample stops being a sample, and both end here rather than in silence:
    a worker disappears with a run in hand, or the whole thing simply stops
    progressing.  The worker check is the sharp one — it fires within a second of the
    loss and names the process — and the deadline is the backstop for everything
    else.
    """
    started_pids = _worker_pids(pool)
    pending = pool.map_async(_worker_task, tasks, chunksize=chunksize)
    deadline = None if timeout is None else time.monotonic() + timeout

    while True:
        pending.wait(WORKER_POLL_SECONDS)
        if pending.ready():
            return Counter(pending.get())

        current_pids = _worker_pids(pool)
        if current_pids != started_pids:
            lost = sorted(set(started_pids) - set(current_pids))
            raise SampleWorkerLost(
                f"sampling {label} lost worker process(es) {lost}: the pool started "
                f"with {started_pids} and now holds {current_pids}. The run those "
                f"workers were executing is gone and its result will never arrive. "
                f"Re-run the same problem with workers=1 to execute it in this "
                f"process, where the failure that killed the worker is visible."
            )

        if deadline is not None and time.monotonic() >= deadline:
            raise SampleStalled(
                f"sampling {label} stalled: {len(tasks)} runs did not finish within "
                f"{timeout:.0f}s, with every worker process still present "
                f"({current_pids}). Sample the same problem with workers=1 to run it "
                f"in this process, and raise or remove the budget with "
                f"{ENV_SAMPLE_TIMEOUT}."
            )


def sample_problem(
    problem: dict,
    n_runs: int,
    seed_offset: int = CHECK_SEED_OFFSET,
    workers: int | None = None,
    max_steps: int = MAX_STEPS,
    run_one: RunOne | None = None,
    pool: ProcessPool | None = None,
    seed_dir: str | None = None,
    timeout: float | None = DERIVE_TIMEOUT,
) -> Counter:
    """Run ``problem`` ``n_runs`` times in discovery mode; count stopping states.

    Frequencies come back because they are useful when reading a failure — how often
    a novel state occurred says a great deal about whether it is old-but-rare or
    newly common — but the comparison in ``check_problem`` is set membership only.

    ``pool`` reuses an existing pool from ``worker_pool``.  The run callable is fixed
    when that pool is created, so passing both is a contradiction and is rejected
    rather than silently resolved.  ``workers=1`` runs in-process, which is the right
    choice for a handful of runs and the only choice for a non-picklable ``run_one``.

    ``timeout`` bounds the wait on the pool: the default derives a budget from
    ``sample_timeout``, ``None`` waits indefinitely, and a number sets the seconds
    directly.  The bounded wait is what makes a stalled sample announce itself, and
    this check is the gate every cognition change is measured against, so it says so
    within the minute rather than holding the suite open.
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
    budget = sample_timeout(n_runs) if timeout == DERIVE_TIMEOUT else timeout
    label = f"{problem.get('name', problem_label(problem))}"

    if pool is not None:
        return _map_within_budget(pool, tasks, chunksize, budget, label)
    with worker_pool(n_workers, run_one, seed_dir) as own_pool:
        return _map_within_budget(own_pool, tasks, chunksize, budget, label)


# ─────────────────────────────────────────────────────────────────────────────
# The comparison
# ─────────────────────────────────────────────────────────────────────────────


def p50_states(record: dict) -> list[str]:
    """The **p50 set**: the smallest group of most-frequent states whose combined
    frequency in the baseline sample reaches 50%.

    These are the states a healthy run reaches routinely, and their absence from a
    sample is a regression rather than sampling noise: the rarest p50 state across
    the 13 problems sits at 20% frequency, whose absence from 100 runs has
    probability 1e-10.

    Read from ``absence_check.states`` where the baseline records it, and otherwise
    computed from the recorded distribution in ``counts`` by the identical rule, so
    a record written by any version of the build script yields the same set.  Ties
    are broken by state name, which makes the derived set deterministic.
    """
    recorded = record.get("absence_check", {}).get("states")
    if recorded is not None:
        return list(recorded)
    counts: dict[str, int] = record.get("counts", {})
    total = sum(counts.values())
    if not total:
        return []
    chosen: list[str] = []
    cumulative = 0
    for state, count in sorted(counts.items(), key=lambda item: (-item[1], item[0])):
        chosen.append(state)
        cumulative += count
        if cumulative / total >= 0.5:
            break
    return chosen


def admitted_range(record: dict) -> set[str]:
    """Every state the baseline accepts: the saturated sample plus admitted states.

    ``expected_range`` is the union of the two as of the last rebuild, and
    ``admitted_states`` is where a state goes when the user adjudicates one that a
    sample surfaced.  Reading both means an adjudication takes effect the moment it
    is written into the fixture.
    """
    return set(record["expected_range"]) | set(record.get("admitted_states", {}))


@dataclass(frozen=True)
class CheckResult:
    """One problem's sample, compared against its baseline record.

    Two outcomes, and they are different kinds of thing:

    * ``missing`` — a p50 state the sample never reached.  A **regression**, and
      ``ok`` is False.
    * ``novel`` — a state outside the baseline's accepted range.  A question **for
      the user to adjudicate**: admit it to the fixture, or treat it as a defect.
      ``ok`` stays True, and ``adjudication`` carries what the decision needs.
    """

    name: str
    label: str
    runs: int
    observed: Counter = field(repr=False)
    #: Observed states outside the baseline's accepted range, with their sample counts.
    novel: dict[str, int]
    #: p50 states the sample failed to produce. Regressions.
    missing: list[str]
    #: p50 states the sample did produce, with their counts.
    present: dict[str, int]
    #: The baseline's f1/N, i.e. the per-check probability of a spurious novel state.
    f1_over_n: float
    #: The numeric backend the sample ran on, as reported by the caller.
    backend: str = "unspecified"
    #: How many states the baseline accepts for this problem.
    baseline_states: int = 0
    #: How many runs the baseline's own sample took.
    baseline_runs: int = 0

    @property
    def ok(self) -> bool:
        """False only for a missing p50 state. Novelty is for the user to decide."""
        return not self.missing

    @property
    def novel_alarm_rate(self) -> float:
        """Probability this sample surfaces at least one always-reachable state the
        baseline had not yet seen, from the baseline's own missing-mass estimate.
        Reported alongside a novel state so it can be read as noise or as signal."""
        return 1.0 - (1.0 - self.f1_over_n) ** self.runs

    def regression(self) -> str:
        """The missing p50 states, as the failure message names them."""
        lines = [
            f"REGRESSION — {self.name} ({self.label}) on the {self.backend} backend "
            f"failed to reach {len(self.missing)} p50 state(s) in {self.runs} runs.",
            "  A p50 state accounts for part of the top half of the baseline's "
            f"distribution over {self.baseline_runs} runs; a healthy engine reaches "
            "it routinely.",
        ]
        lines.extend(f"    NOT REACHED  {state}" for state in self.missing)
        if self.present:
            lines.append("  p50 states that were reached:")
            lines.extend(
                f"    {state}  x{count}" for state, count in sorted(self.present.items())
            )
        return "\n".join(lines)

    def adjudication(self) -> str:
        """The novel states, with everything the user's decision needs.

        Which problem, which state, which backend, how many samples, and how likely
        the baseline's own saturation says such a state is by chance.
        """
        lines = [
            f"ADJUDICATE — {self.name} ({self.label}) on the {self.backend} backend "
            f"reached {len(self.novel)} state(s) that "
            f"tests/fixtures/expected_range.json does not list.",
            f"  Sample: {self.runs} runs, {len(self.observed)} distinct states. "
            f"Baseline: {self.baseline_runs} runs, {self.baseline_states} states.",
            f"  A state the baseline had never seen appears by chance in "
            f"~{self.novel_alarm_rate:.1%} of samples of this problem at this size.",
        ]
        lines.extend(
            f"    NOVEL  {state}  x{count} of {self.runs}"
            for state, count in sorted(self.novel.items())
        )
        lines.append(
            "  Decide: admit it under this problem's admitted_states in the fixture, "
            "or treat it as a defect. Re-sample deeply first with "
            f"scripts/build_expected_range.py --problem {self.name} --force."
        )
        return "\n".join(lines)

    def describe(self) -> str:
        lines = [
            f"{self.name}  ({self.label})  backend={self.backend}  {self.runs} runs, "
            f"{len(self.observed)} distinct stopping states"
        ]
        if self.missing:
            lines.append(self.regression())
        elif self.present:
            lines.append("  p50 states present:")
            lines.extend(
                f"    {state}  x{count}" for state, count in sorted(self.present.items())
            )
        if self.novel:
            lines.append(self.adjudication())
        return "\n".join(lines)


def check_problem(
    record: dict, observed: Counter, backend: str = "unspecified"
) -> CheckResult:
    """Compare a sample against one baseline record.

    Set membership only: the baseline's own frequencies are never compared against
    the sample's, because reordering codelets moves frequencies around freely without
    changing which states are reachable, and a frequency test would fire on every
    such change while telling us nothing about correctness.  The one place frequency
    enters is the choice of p50 set, and that is the *baseline's* distribution
    deciding which states are common enough for their absence to mean something.

    ``backend`` is carried through so a difference names the configuration that
    produced it.  Every difference, on every backend, is reported; a state is added
    to the fixture only by the user's decision.
    """
    expected = admitted_range(record)
    common = p50_states(record)
    runs = sum(observed.values())

    novel = {state: count for state, count in observed.items() if state not in expected}
    missing = [state for state in common if state not in observed]
    present = {state: observed[state] for state in common if state in observed}

    return CheckResult(
        name=record["name"],
        label=problem_label(record),
        runs=runs,
        observed=observed,
        novel=novel,
        missing=missing,
        present=present,
        f1_over_n=record.get("f1_over_n", 0.0),
        backend=backend,
        baseline_states=len(expected),
        baseline_runs=record.get("runs", 0),
    )


def check_all(
    baseline: Baseline,
    n_runs: int,
    workers: int | None = None,
    run_one: RunOne | None = None,
    names: Sequence[str] | None = None,
    progress: Callable[[CheckResult], None] | None = None,
    backends: Sequence[str] | None = None,
) -> list[CheckResult]:
    """Check every problem in the baseline over a single shared pool.

    The pytest entry point parametrises over problems instead, so each shows up as
    its own test; this is for scripts and for interactive use, where one call and one
    pool is easier than driving pytest.
    """
    records = [baseline.by_name(n) for n in names] if names else list(baseline)
    results: list[CheckResult] = []
    backend = resolved_worker_backend(backends)
    with worker_pool(workers, run_one, backends=backends) as pool:
        for record in records:
            observed = sample_problem(record, n_runs, pool=pool)
            result = check_problem(record, observed, backend=backend)
            results.append(result)
            if progress is not None:
                progress(result)
    return results
