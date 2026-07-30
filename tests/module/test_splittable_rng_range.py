"""The engine reaches the same expected range under the splittable RNG (WP4.1).

This is the plan's stated verification, and it is also the **first real test of the
oracle itself**.  The whole expected-range approach rests on a claim: that changing the
random stream changes *which* answer a given seed produces and *how often* each occurs,
but not *which answers are reachable*.  Replacing the generator outright is the
sharpest available test of that claim, and a moving set here would have been a finding
about the oracle rather than about the RNG — something to understand before any of
Stage 4 continued.

The set does not move.

The check runs the standard machinery from ``tests/support/expected_range.py`` with a
``run_one`` that swaps the generator, which is exactly what the ``run_one`` seam exists
for.
"""

from __future__ import annotations

import os

import pytest

from server.engine.metadata import MetadataProvider
from server.engine.runner import EngineRunner
from server.engine.splittable_rng import SplittableRNG

from tests.support.expected_range import (
    MAX_STEPS,
    check_problem,
    load_baseline,
    problem_label,
    sample_problem,
    worker_pool,
)

#: Runs per problem. Lower than the routine check's 100 would not be worth doing; the
#: default matches it, and PETACAT_RNG_RANGE_RUNS raises it for a deeper look.
RUNS = int(os.environ.get("PETACAT_RNG_RANGE_RUNS", "100"))


def run_one_splittable(
    meta: MetadataProvider, problem: dict, seed: int, max_steps: int
) -> str:
    """One discovery run with the counter-based generator in place of the stateful one.

    The swap is wholesale and needs no other change, because the engine already takes
    its generator from the context rather than reaching for a global — which is what the
    deliberately API-compatible surface on ``SplittableRNG`` was for. The coderack keeps
    its own reference for capacity enforcement, so that one is repointed too.

    Module-level because the worker pool pickles it.
    """
    runner = EngineRunner(meta)
    runner.init_mcat(
        problem["initial"], problem["modified"], problem["target"], seed=seed
    )
    runner.ctx.rng = SplittableRNG(seed)
    runner.ctx.coderack.rng = runner.ctx.rng
    runner.run_mcat(max_steps=max_steps)
    workspace = runner.ctx.workspace
    answer = workspace.answer_string.text if workspace.answer_string else ""
    return f"{runner.status}:{answer}"


@pytest.mark.slow
def test_expected_range_is_unchanged_under_the_splittable_rng():
    """No frequent state lost, on any problem, with a completely different stream.

    Novel states are reported rather than failed, as everywhere else — the baseline is
    saturated but not exhaustive, and at f1/N = 0.0001 a 100-run check surfaces an
    always-reachable state about 1% of the time per problem.
    """
    baseline = load_baseline()
    missing: list[str] = []
    novel: list[str] = []

    with worker_pool(run_one=run_one_splittable) as pool:
        for record in baseline:
            observed = sample_problem(record, RUNS, pool=pool, max_steps=MAX_STEPS)
            result = check_problem(record, observed)
            if result.missing:
                missing.append(f"{problem_label(record)}: {result.missing}")
            if result.novel:
                novel.append(f"{problem_label(record)}: {sorted(result.novel)}")

    if novel:
        pytest.warns  # documented: novelty is a prompt to investigate, not a failure
        print("novel states under the splittable RNG (investigate, not a failure):")
        for line in novel:
            print(f"  {line}")

    assert not missing, (
        "The splittable RNG lost a frequent stopping state. Either the generator is "
        "biased, or the oracle's premise — that the reachable set does not depend on "
        "the random stream — is wrong. Both need understanding before Stage 4 "
        "continues.\n  " + "\n  ".join(missing)
    )


def test_the_swap_needs_no_engine_changes():
    """The compatibility surface is the point, so it is asserted rather than assumed.

    If a method were missing, the range check above would fail with an AttributeError
    from inside a worker process, which is a much worse way to find out.
    """
    from server.engine.rng import RNG

    original = {n for n in dir(RNG) if not n.startswith("_")}
    replacement = {n for n in dir(SplittableRNG) if not n.startswith("_")}
    assert original <= replacement, f"missing: {sorted(original - replacement)}"


def test_a_short_run_completes_with_the_splittable_rng():
    """A cheap smoke test, so the unmarked suite still exercises the swap."""
    seed_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "seed_data",
    )
    meta = MetadataProvider.from_seed_data(seed_dir)
    state = run_one_splittable(meta, {"initial": "abc", "modified": "abd",
                                      "target": "xyz"}, seed=42, max_steps=2000)
    status, _, _answer = state.partition(":")
    assert status in {"answer_found", "halted", "gave_up"}
