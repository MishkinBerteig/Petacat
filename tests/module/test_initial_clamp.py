"""The initial Slipnet clamp is Metacat's, in every way a run is executed (``run.ss:151-154, 268-273``).

At the clamp the two initially clamped concepts go to full activation and freeze; the
release time is the codelet count then plus ``initial_slipnode_clamp_cycles`` x
``update_cycle_length``; they unfreeze when the codelet count reaches it.  That holds at
the start of a Run and whenever the Coderack empties and the clamp is re-applied, which
need not be on an update boundary, so the release codelet is checked exactly: off a
boundary, serially, free-running and speculatively, and across a capture and a restore.
"""

from __future__ import annotations

import json
import os

import pytest

from server.engine.metadata import MetadataProvider
from server.engine.runner import EngineRunner
from server.engine.state_graph import capture_run_state, restore_run_state

# Every test here executes arithmetic the numeric substrate owns, so each one runs
# once per backend in the matrix. See tests/conftest.py.
pytestmark = pytest.mark.numeric_matrix

SEED_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "seed_data",
)

PROBLEM = ("abc", "abd", "xyz")
SEED = 7
#: 50 update cycles of 15 codelets.
CLAMP_LENGTH = 750
#: A codelet count that is not a multiple of the update cycle length (15).
OFF_BOUNDARY = 1003
INITIAL_NODES = ("plato-letter-category", "plato-string-position-category")


@pytest.fixture(scope="module")
def meta() -> MetadataProvider:
    return MetadataProvider.from_standard_configuration(SEED_DIR)


def _fresh(meta) -> EngineRunner:
    runner = EngineRunner(meta)
    runner.init_mcat(*PROBLEM, seed=SEED)
    return runner


def _frozen(runner) -> list[bool]:
    return [runner.ctx.slipnet.nodes[n].frozen for n in INITIAL_NODES]


def _step_to(runner, count: int) -> None:
    while runner.ctx.codelet_count < count:
        runner.step_mcat()


def _watch_release(runner) -> list[int]:
    """Record the codelet count of every release of the initial clamp."""
    released: list[int] = []
    real = runner._unclamp_initial_slipnodes

    def record(slipnet):
        released.append(runner.ctx.codelet_count)
        real(slipnet)

    runner._unclamp_initial_slipnodes = record
    return released


def _empty_the_rack_at(runner, count: int) -> None:
    """Run to *count*, then empty the Coderack: the next step re-applies the clamp there."""
    _step_to(runner, count)
    assert count % runner.meta.get_param("update_cycle_length") != 0
    runner.ctx.coderack.clear()
    assert runner.ctx.coderack.is_empty


def test_the_opening_clamp_releases_at_the_fixed_codelet(meta):
    runner = _fresh(meta)
    assert runner.ctx.initial_unclamp_time == CLAMP_LENGTH
    assert all(_frozen(runner))
    _step_to(runner, CLAMP_LENGTH - 1)
    assert all(_frozen(runner))
    runner.step_mcat()
    assert runner.ctx.codelet_count == CLAMP_LENGTH
    assert not any(_frozen(runner))


def test_a_clamp_re_applied_off_an_update_boundary_releases_at_the_exact_codelet(meta):
    runner = _fresh(meta)
    released = _watch_release(runner)
    _empty_the_rack_at(runner, OFF_BOUNDARY)
    assert not any(_frozen(runner))  # released at 750, long before

    runner.step_mcat()  # the empty Coderack is refilled and the clamp re-applied at 1003
    assert runner.ctx.initial_unclamp_time == OFF_BOUNDARY + CLAMP_LENGTH
    assert all(_frozen(runner))
    release_at = OFF_BOUNDARY + CLAMP_LENGTH
    _step_to(runner, release_at - 1)
    assert all(_frozen(runner))
    runner.step_mcat()
    assert runner.ctx.codelet_count == release_at
    assert not any(_frozen(runner))
    assert released == [CLAMP_LENGTH, release_at]


def test_free_running_re_applies_the_clamp_with_the_same_rule(meta):
    from server.parallel.free_running import run_free

    runner = _fresh(meta)
    released = _watch_release(runner)
    _empty_the_rack_at(runner, OFF_BOUNDARY)

    run_free(runner, workers=1, max_steps=OFF_BOUNDARY + CLAMP_LENGTH + 20)

    assert released == [CLAMP_LENGTH, OFF_BOUNDARY + CLAMP_LENGTH]
    assert not any(_frozen(runner))


def test_the_speculative_executor_releases_at_the_same_codelets_as_the_serial_loop(meta):
    from server import parallel

    def release_counts(executor_name: str, **options) -> list[int]:
        runner = _fresh(meta)
        released = _watch_release(runner)
        _empty_the_rack_at(runner, OFF_BOUNDARY)
        parallel.get_executor(executor_name)(runner, **options).run(
            OFF_BOUNDARY + CLAMP_LENGTH + 20
        )
        return released

    serial = release_counts("stream")
    assert serial == [CLAMP_LENGTH, OFF_BOUNDARY + CLAMP_LENGTH]
    assert release_counts("speculative", workers=2, use_qos=False) == serial


@pytest.mark.parametrize("captured_at", [300, 749, OFF_BOUNDARY + 100])
def test_a_run_captured_and_restored_releases_at_the_same_codelet(meta, captured_at):
    """A capture taken after a clamp and before its release must release when the original does."""
    original = _fresh(meta)
    if captured_at > CLAMP_LENGTH:
        _empty_the_rack_at(original, OFF_BOUNDARY)
    _step_to(original, captured_at)
    state = json.loads(json.dumps(capture_run_state(original.ctx)))
    assert state["runner"]["initial_unclamp_time"] == original.ctx.initial_unclamp_time
    release_at = original.ctx.initial_unclamp_time
    assert release_at > captured_at and all(_frozen(original))

    restored = EngineRunner(meta)
    restored.init_mcat(*PROBLEM, seed=SEED)
    restore_run_state(restored, state)
    assert restored.ctx.initial_unclamp_time == release_at
    assert all(_frozen(restored))

    released = _watch_release(restored)
    _step_to(restored, release_at - 1)
    assert all(_frozen(restored))
    restored.step_mcat()
    assert restored.ctx.codelet_count == release_at
    assert not any(_frozen(restored))
    assert released == [release_at]
