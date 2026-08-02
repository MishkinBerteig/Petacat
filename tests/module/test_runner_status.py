"""The status an ``EngineRunner`` reports as a run moves through it."""

import os
import pytest

from server.engine.metadata import MetadataProvider
from server.engine.runner import (
    EngineRunner,
    STATUS_GAVE_UP,
    STATUS_HALTED,
    STATUS_INITIALIZED,
)


SEED_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "seed_data")


@pytest.fixture
def meta():
    return MetadataProvider.from_seed_data(SEED_DIR)


def test_initial_status(meta):
    runner = EngineRunner(meta)
    assert runner.status == STATUS_INITIALIZED


def test_init_mcat_sets_initialized(meta):
    runner = EngineRunner(meta)
    runner.init_mcat("abc", "abd", "xyz", seed=42)
    assert runner.status == STATUS_INITIALIZED


def test_run_mcat_sets_running_then_halted(meta):
    runner = EngineRunner(meta)
    runner.init_mcat("abc", "abd", "xyz", seed=42)
    result = runner.run_mcat(max_steps=10)
    assert result.status == STATUS_HALTED


def test_status_is_plain_string(meta):
    """Status should be a plain string, not an Enum — no .name or .value needed."""
    runner = EngineRunner(meta)
    runner.init_mcat("abc", "abd", "xyz", seed=42)
    # Direct string comparison (no .name.lower() needed)
    assert runner.status == "initialized"
    runner.run_mcat(max_steps=10)
    assert runner.status == "halted"


def test_repr_contains_status_string(meta):
    runner = EngineRunner(meta)
    runner.init_mcat("abc", "abd", "xyz", seed=42)
    assert "initialized" in repr(runner)


def test_giving_up_is_reported_on_the_step_result(meta):
    """Giving up has to be visible to the caller, not just recorded internally.

    §4.5.2: giving up is a considered outcome, distinct from running out of
    codelets.  The step result is the only channel the API — and therefore the
    display — has for telling the two apart, so the flag has to travel on it.
    """
    from server.engine.codelet_dsl.builtins import give_up

    runner = EngineRunner(meta)
    runner.init_mcat("abc", "abd", "xyz", seed=42)

    # An ordinary step neither gives up nor claims to.
    ordinary = runner.step_mcat()
    assert ordinary.gave_up is False

    # A jootser calling give_up ends the very next step.
    give_up(runner.ctx)
    result = runner.step_mcat()
    assert result.gave_up is True
    assert runner.status == STATUS_GAVE_UP

    # And the flag is consumed, not sticky.
    assert getattr(runner.ctx, "_gave_up", False) is False
