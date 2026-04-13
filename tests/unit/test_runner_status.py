"""Tests for EngineRunner with string status constants."""

import os
import pytest

from server.engine.metadata import MetadataProvider
from server.engine.runner import (
    EngineRunner,
    STATUS_ANSWER_FOUND,
    STATUS_GAVE_UP,
    STATUS_HALTED,
    STATUS_INITIALIZED,
    STATUS_PAUSED,
    STATUS_RUNNING,
)


SEED_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "seed_data")


@pytest.fixture
def meta():
    return MetadataProvider.from_seed_data(SEED_DIR)


def test_status_constants_are_strings():
    assert isinstance(STATUS_INITIALIZED, str)
    assert isinstance(STATUS_RUNNING, str)
    assert isinstance(STATUS_PAUSED, str)
    assert isinstance(STATUS_ANSWER_FOUND, str)
    assert isinstance(STATUS_HALTED, str)
    assert isinstance(STATUS_GAVE_UP, str)


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
