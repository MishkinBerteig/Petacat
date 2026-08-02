"""Population batching (WP4.6).

The unit here is *runs per second*, not codelets per second.  Corpus training,
evolutionary search and the expected-range oracle are all bounded by how many complete
runs an hour buys, and a change that makes one run faster while halving how many fit on
the machine is a loss for all three.

The properties worth pinning are that the two strategies agree about what a run *is* —
otherwise a population measured one way cannot be compared with one measured the other —
and that the batching threshold is a measured predicate rather than an assumption.
"""

from __future__ import annotations

import os

import pytest

from server.engine.metadata import MetadataProvider
from server.engine.population import (
    BATCHING_MIN_NODES,
    batching_is_worthwhile,
    run_population,
    run_population_batched,
    stopping_state,
)
from server.engine.runner import EngineRunner

# Every test here executes arithmetic the numeric substrate owns, so each one runs
# once per backend in the matrix. See tests/conftest.py.
pytestmark = pytest.mark.numeric_matrix

SEED_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "seed_data",
)
PROBLEM = ("abc", "abd", "mrrjjj")


@pytest.fixture(scope="module")
def meta() -> MetadataProvider:
    return MetadataProvider.from_seed_data(SEED_DIR)


def test_the_two_strategies_produce_the_same_stopping_states(meta):
    """The decisive property.

    Process-parallel and batched lockstep must be two ways of executing the same runs, not
    two different experiments. Same seeds, same problem, same states — otherwise a
    population measured one way could not be compared with one measured the other, and the
    oracle's baseline (built process-parallel) would not apply to a batched population.
    """
    by_process = run_population(PROBLEM, 8, seed_offset=500, workers=2, max_steps=3000)
    batched = run_population_batched(PROBLEM, 8, seed_offset=500, max_steps=3000, meta=meta)
    assert by_process.states == batched.states


def test_a_population_matches_running_each_seed_alone(meta):
    """Neither strategy may perturb a run.

    Batched lockstep in particular interleaves K runs in one process, so a shared global
    anywhere in the engine would show up here as a population whose results depend on its
    size. WP0.3 removed the identifier counters that would have done exactly that.
    """
    expected = []
    for seed in range(300, 306):
        runner = EngineRunner(meta)
        runner.init_mcat(*PROBLEM, seed=seed)
        runner.run_mcat(max_steps=3000)
        expected.append(stopping_state(runner))

    batched = run_population_batched(PROBLEM, 6, seed_offset=300, max_steps=3000, meta=meta)
    assert batched.states == expected


def test_population_size_does_not_change_any_run(meta):
    """A run's outcome must not depend on how many other runs it was batched with."""
    small = run_population_batched(PROBLEM, 4, seed_offset=700, max_steps=3000, meta=meta)
    large = run_population_batched(PROBLEM, 12, seed_offset=700, max_steps=3000, meta=meta)
    assert large.states[:4] == small.states


def test_stopping_state_matches_the_oracle_key(meta):
    """The engine's key and the checker's must agree.

    They are written out separately on purpose — the engine must not import the test tree
    — so their agreement is a property to test rather than something the import guarantees.
    """
    from tests.support.expected_range import default_run_one

    problem = {"initial": PROBLEM[0], "modified": PROBLEM[1], "target": PROBLEM[2]}
    from_checker = default_run_one(meta, problem, 42, 3000)

    runner = EngineRunner(meta)
    runner.init_mcat(*PROBLEM, seed=42)
    runner.run_mcat(max_steps=3000)
    assert stopping_state(runner) == from_checker


def test_batching_threshold_is_a_measured_predicate():
    """A predicate rather than a policy buried in the loop, so it can be re-measured.

    The threshold comes from WP4.5's crossover: below ~10,000 nodes a Metal dispatch costs
    more than the numeric work it would carry, so batching K runs into one kernel is slower
    than doing all K on the CPU.
    """
    assert not batching_is_worthwhile(59)
    assert not batching_is_worthwhile(BATCHING_MIN_NODES - 1)
    assert batching_is_worthwhile(BATCHING_MIN_NODES)
    assert batching_is_worthwhile(300_000)


def test_batching_is_not_worthwhile_at_the_current_slipnet(meta):
    """Recorded as a fact about today's engine, so it is revisited when the Slipnet grows.

    Measured: at 59 nodes, process-parallel reaches 70.8 runs/s at K=128 while batched
    lockstep stays flat near 12 — because lockstep holds every finished run hostage to the
    batch's slowest, and the demo problems' run lengths differ by an order of magnitude.
    """
    assert not batching_is_worthwhile(len(meta.slipnet_node_specs))


def test_the_batching_seam_sees_every_live_runner(meta):
    """``on_cycle`` is where a batched GPU kernel would go.

    It is a seam rather than an implementation because there is nothing to gain at 59
    nodes, but it has to be handed the right thing or it will not be usable when there is:
    every runner still executing, at a shared update-cycle boundary.
    """
    seen: list[int] = []

    def on_cycle(runners):
        seen.append(len(runners))
        counts = {r.ctx.codelet_count for r in runners}
        # The point of lockstep: all live runs sit at the same codelet count, which is
        # what lets their numeric work be presented as one batch.
        assert len(counts) == 1, counts

    run_population_batched(
        PROBLEM, 4, seed_offset=900, max_steps=600, meta=meta, on_cycle=on_cycle
    )
    assert seen
    assert seen[0] == 4
    # Runs drop out as they finish, so the population never grows.
    assert seen == sorted(seen, reverse=True)


def test_process_parallel_returns_one_state_per_run(meta):
    result = run_population(PROBLEM, 6, seed_offset=1200, workers=2, max_steps=2000)
    assert result.runs == 6
    assert len(result.states) == 6
    assert all(":" in state for state in result.states)
    assert result.runs_per_second > 0


def test_summaries_report_what_a_population_costs(meta):
    result = run_population_batched(PROBLEM, 4, seed_offset=1300, max_steps=1500, meta=meta)
    summary = result.summary()
    assert summary["strategy"] == "batched"
    assert summary["runs"] == 4
    assert summary["distinct_states"] >= 1
    assert summary["runs_per_second"] > 0
