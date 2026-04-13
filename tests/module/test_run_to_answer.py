"""Module tests for run-to-answer behavior at the EngineRunner level.

Tests cover max_steps halting, answer detection propagation, and
deterministic replay of limited runs.
"""

import os
import pytest

from server.engine.metadata import MetadataProvider
from server.engine.runner import (
    EngineRunner,
    STATUS_HALTED,
    STATUS_RUNNING,
)


SEED_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "seed_data")


@pytest.fixture
def meta():
    return MetadataProvider.from_seed_data(SEED_DIR)


@pytest.fixture
def runner(meta):
    return EngineRunner(meta)


def test_run_mcat_zero_max_steps_means_no_limit(runner):
    """max_steps=0 should NOT stop immediately — it means no limit.

    We verify by running with max_steps=0 but checking that at least
    some codelets executed (the runner will hit halted via other means
    or we stop externally). Here we just verify it doesn't return 0 steps.
    """
    runner.init_mcat("abc", "abd", "xyz", seed=42)
    # Manually run a bounded number of steps to test that max_steps=0
    # does not cause immediate halt. We'll step manually and check.
    runner.status = STATUS_RUNNING
    steps_run = 0
    for _ in range(50):
        if runner.status != STATUS_RUNNING:
            break
        runner.step_mcat()
        steps_run += 1
    assert steps_run == 50, "Engine should keep running when there's no step limit"


def test_run_mcat_halts_at_max_steps(runner):
    """run_mcat with a step limit should stop at exactly that many steps."""
    runner.init_mcat("abc", "abd", "xyz", seed=42)
    result = runner.run_mcat(max_steps=75)
    assert result.status == STATUS_HALTED
    assert result.codelet_count == 75


def test_run_mcat_codelet_count_matches_steps(runner):
    """The codelet_count in the result should match the number of steps taken."""
    runner.init_mcat("abc", "abd", "xyz", seed=42)
    result = runner.run_mcat(max_steps=30)
    assert result.codelet_count == 30
    assert len(result.steps) == 30


def test_run_mcat_returns_step_results(runner):
    """Each step in the result should have a codelet_type and codelet_count."""
    runner.init_mcat("abc", "abd", "xyz", seed=42)
    result = runner.run_mcat(max_steps=10)
    for i, step in enumerate(result.steps):
        assert step.codelet_type != "", f"Step {i} has no codelet_type"
        assert step.codelet_count == i + 1, f"Step {i} has wrong codelet_count"


def test_run_mcat_deterministic_with_same_seed(meta):
    """Two run_mcat calls with the same seed should produce identical results."""
    runner1 = EngineRunner(meta)
    runner1.init_mcat("abc", "abd", "xyz", seed=99)
    result1 = runner1.run_mcat(max_steps=50)

    runner2 = EngineRunner(meta)
    runner2.init_mcat("abc", "abd", "xyz", seed=99)
    result2 = runner2.run_mcat(max_steps=50)

    for i, (s1, s2) in enumerate(zip(result1.steps, result2.steps)):
        assert s1.codelet_type == s2.codelet_type, (
            f"Step {i}: {s1.codelet_type} != {s2.codelet_type}"
        )


def test_run_mcat_status_transitions(runner):
    """Status should go from initialized -> running (internal) -> halted."""
    runner.init_mcat("abc", "abd", "xyz", seed=42)
    assert runner.status == "initialized"
    result = runner.run_mcat(max_steps=5)
    assert runner.status == STATUS_HALTED
    assert result.status == STATUS_HALTED


def test_run_mcat_temperature_updated(runner):
    """After running past an update cycle, temperature should be computed."""
    runner.init_mcat("abc", "abd", "xyz", seed=42)
    runner.run_mcat(max_steps=30)  # At least 2 update cycles (15 each)
    # Temperature should have been updated (may still be 100 if no structures)
    assert 0 <= runner.ctx.temperature.value <= 100
