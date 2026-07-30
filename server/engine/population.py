"""Population batching — K independent runs advanced together (WP4.6).

Phase 4's corpus training, Phase 6's evolution and the expected-range oracle all want the
same thing: not one run made faster, but *many runs* made cheap.  The oracle already
depends on it — 410,000 runs built the baseline, and a routine check is 1,300 — and
evolution needs hundreds of runs per configuration because a free-running run is one draw
rather than a reproducible trace.

Two ways to get there, and they are not alternatives
-----------------------------------------------------
**Process-parallel** (:func:`run_population`) is what the oracle uses today: K runs across
a process pool, one interpreter each.  It scales with cores, needs no thread safety at all
because nothing is shared, and it is the right answer whenever the work is CPU-bound
Python — which at today's 59-node Slipnet it entirely is.

**Batched** (:func:`run_population_batched`) advances K runs in lockstep so their numeric
work can be presented to the GPU as one fat kernel instead of K thin ones.  That is the
arrangement WP4.5 measured the case for: a Metal dispatch costs ~0.2 ms whether it touches
200 edges or 340,000, so K runs batched into one dispatch pay once rather than K times.

**At 59 nodes, batching cannot pay and the honest thing is to say so.** The numeric
substrate is 0.007 ms per update cycle on vectorised CPU; batching 128 of those into one
0.2 ms GPU dispatch is slower than doing all 128 on the CPU. The batched path exists
because the Slipnet is going to grow — the plan targets ~300,000 nodes — and because the
crossover has been measured rather than guessed: WP4.5 puts it at ~10⁴ nodes for the
kernel. Below that, ``run_population`` is the answer and ``run_population_batched`` says
so rather than pretending otherwise.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Callable, Sequence

from server.engine.metadata import MetadataProvider
from server.engine.runner import EngineRunner

#: Below this many Slipnet nodes, batching the numeric substrate cannot repay a GPU
#: dispatch. Measured in WP4.5: the kernel crossover against vectorised float64 CPU is
#: around 10^4 nodes, and the whole-update crossover is between 10^4 and 10^5.
BATCHING_MIN_NODES = 10_000


@dataclass
class PopulationResult:
    """The stopping states of K runs, and what the population cost."""

    states: list[str] = field(default_factory=list)
    seconds: float = 0.0
    runs: int = 0
    workers: int = 1
    strategy: str = "process"

    @property
    def runs_per_second(self) -> float:
        return self.runs / self.seconds if self.seconds else 0.0

    def summary(self) -> dict:
        return {
            "strategy": self.strategy,
            "runs": self.runs,
            "workers": self.workers,
            "seconds": round(self.seconds, 3),
            "runs_per_second": round(self.runs_per_second, 1),
            "distinct_states": len(set(self.states)),
        }


def stopping_state(runner: EngineRunner) -> str:
    """``status:answer`` — the same key the oracle uses.

    Duplicated from ``tests/support/expected_range`` deliberately rather than imported:
    the engine must not depend on the test tree, and the two agreeing is a property worth
    a test rather than an import.
    """
    workspace = runner.ctx.workspace
    answer = workspace.answer_string.text if workspace.answer_string else ""
    return f"{runner.status}:{answer}"


_META: MetadataProvider | None = None


def _init_worker(seed_dir: str) -> None:
    global _META
    _META = MetadataProvider.from_seed_data(seed_dir)


def _run_one(task: tuple) -> str:
    problem, seed, max_steps = task
    runner = EngineRunner(_META)
    runner.init_mcat(problem[0], problem[1], problem[2], seed=seed)
    runner.run_mcat(max_steps=max_steps)
    return stopping_state(runner)


def run_population(
    problem: Sequence[str],
    count: int,
    seed_offset: int = 0,
    workers: int | None = None,
    max_steps: int = 6000,
    seed_dir: str | None = None,
) -> PopulationResult:
    """K independent runs across a process pool.

    Nothing is shared, so there is no thread safety to get right and no contention to
    measure — which is exactly why this is the right tool for a population and
    free-running is the right tool for a single run. The two solve different problems and
    compose: a population of free-running runs is possible but pointless, because the
    cores are already busy.
    """
    import time
    from multiprocessing import Pool

    seed_dir = seed_dir or os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "seed_data",
    )
    workers = workers or max(1, (os.cpu_count() or 4) - 1)
    tasks = [
        (tuple(problem), seed_offset + i, max_steps) for i in range(count)
    ]

    started = time.perf_counter()
    if workers == 1:
        _init_worker(seed_dir)
        states = [_run_one(t) for t in tasks]
    else:
        chunk = max(1, count // (workers * 4))
        with Pool(workers, initializer=_init_worker, initargs=(seed_dir,)) as pool:
            states = list(pool.map(_run_one, tasks, chunksize=chunk))
    elapsed = time.perf_counter() - started

    return PopulationResult(
        states=states, seconds=elapsed, runs=count, workers=workers, strategy="process"
    )


def batching_is_worthwhile(node_count: int) -> bool:
    """Would presenting K runs' numeric work as one kernel repay the dispatch?

    A predicate rather than a policy buried in the batching loop, so the answer is
    inspectable and so the threshold can be re-measured rather than argued about.
    """
    return node_count >= BATCHING_MIN_NODES


def run_population_batched(
    problem: Sequence[str],
    count: int,
    seed_offset: int = 0,
    max_steps: int = 6000,
    meta: MetadataProvider | None = None,
    on_cycle: Callable[[list[EngineRunner]], None] | None = None,
) -> PopulationResult:
    """Advance K runs in lockstep, so their numeric work can be batched.

    Every run is stepped one codelet at a time in turn, which puts all K at the same
    codelet count and therefore at the same update-cycle boundary — the point at which
    their Slipnet spreading, object values and structure strengths could be presented to
    the GPU as one batched kernel rather than K separate dispatches.

    ``on_cycle`` is the seam where that batching would happen: it is handed every live
    runner at each boundary. It is a seam rather than an implementation because **at 59
    nodes there is nothing to gain** — see the module docstring and
    :func:`batching_is_worthwhile`. Building the batched kernel now would mean shipping
    an unmeasurable optimisation and a second numeric code path to keep correct.

    Lockstep costs something even so: a run that would have finished in 300 codelets is
    held in the population until the batch's slowest reaches its own ending, so K runs
    take as long as the longest rather than the mean. On the demo problems the spread is
    wide — some answer in 200 codelets and some exhaust 6,000 — which is the second reason
    process-parallel wins today.
    """
    import time

    meta = meta or MetadataProvider.from_seed_data(
        os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            "seed_data",
        )
    )
    update_cycle = meta.get_param("update_cycle_length", 15)

    runners: list[EngineRunner] = []
    for index in range(count):
        runner = EngineRunner(meta)
        runner.init_mcat(problem[0], problem[1], problem[2], seed=seed_offset + index)
        runner.status = "running"
        runners.append(runner)

    started = time.perf_counter()
    live = list(runners)
    step = 0
    while live and step < max_steps:
        for runner in live:
            runner.step_mcat()
        step += 1
        if on_cycle is not None and step % update_cycle == 0:
            on_cycle(live)
        live = [r for r in live if r.status == "running"]

    for runner in runners:
        if runner.status == "running":
            runner.status = "halted"
        runner.finish()
    elapsed = time.perf_counter() - started

    return PopulationResult(
        states=[stopping_state(r) for r in runners],
        seconds=elapsed,
        runs=count,
        workers=1,
        strategy="batched",
    )
