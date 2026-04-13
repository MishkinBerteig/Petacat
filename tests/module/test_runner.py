"""Module integration tests for EngineRunner."""

import os
import pytest
from server.engine.metadata import MetadataProvider
from server.engine.runner import EngineRunner, STATUS_HALTED
from server.engine.memory import EpisodicMemory


SEED_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "seed_data")


@pytest.fixture
def meta():
    return MetadataProvider.from_seed_data(SEED_DIR)


@pytest.fixture
def runner(meta):
    return EngineRunner(meta)


def test_init_mcat(runner):
    runner.init_mcat("abc", "abd", "xyz", seed=42)
    assert runner.ctx is not None
    assert runner.ctx.workspace.initial_string.text == "abc"
    assert runner.ctx.workspace.modified_string.text == "abd"
    assert runner.ctx.workspace.target_string.text == "xyz"
    assert runner.ctx.codelet_count == 0
    assert not runner.ctx.justify_mode


def test_init_mcat_justify_mode(runner):
    runner.init_mcat("abc", "abd", "xyz", answer="wyz", seed=42)
    assert runner.ctx.justify_mode


def test_init_posts_codelets(runner):
    runner.init_mcat("abc", "abd", "xyz", seed=42)
    # Should have posted 2 * 9 = 18 initial codelets (9 objects)
    assert runner.ctx.coderack.total_count == 18


def test_step_mcat(runner):
    runner.init_mcat("abc", "abd", "xyz", seed=42)
    result = runner.step_mcat()
    assert result.codelet_count == 1
    assert result.codelet_type != ""


def test_run_mcat_limited_steps(runner):
    runner.init_mcat("abc", "abd", "xyz", seed=42)
    result = runner.run_mcat(max_steps=100)
    assert result.codelet_count == 100
    assert result.status == STATUS_HALTED


def test_deterministic_replay(meta):
    """Same seed should produce identical codelet sequences."""
    runner1 = EngineRunner(meta)
    runner1.init_mcat("abc", "abd", "xyz", seed=12345)

    runner2 = EngineRunner(meta)
    runner2.init_mcat("abc", "abd", "xyz", seed=12345)

    for _ in range(50):
        r1 = runner1.step_mcat()
        r2 = runner2.step_mcat()
        assert r1.codelet_type == r2.codelet_type
        assert r1.codelet_count == r2.codelet_count


def test_update_cycle_fires(runner):
    """Update should fire every 15 codelets."""
    runner.init_mcat("abc", "abd", "xyz", seed=42)
    for _ in range(15):
        runner.step_mcat()
    # After 15 steps, temperature should have been updated
    assert runner.ctx.temperature.value <= 100


def test_slipnet_clamped_on_init(runner):
    runner.init_mcat("abc", "abd", "xyz", seed=42)
    lc = runner.ctx.slipnet.get_node("plato-letter-category")
    sp = runner.ctx.slipnet.get_node("plato-string-position-category")
    assert lc.frozen
    assert sp.frozen


def test_shared_memory_across_runs(meta):
    """Episodic memory persists across runs."""
    memory = EpisodicMemory()
    runner = EngineRunner(meta)

    runner.init_mcat("abc", "abd", "xyz", seed=42, memory=memory)
    runner.run_mcat(max_steps=10)

    runner.init_mcat("rst", "rsu", "xyz", seed=99, memory=memory)
    assert runner.ctx.memory is memory
