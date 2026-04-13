"""Tests for Temperature."""

import os
import pytest
from server.engine.temperature import Temperature
from server.engine.metadata import MetadataProvider


SEED_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "seed_data")


@pytest.fixture
def meta():
    return MetadataProvider.from_seed_data(SEED_DIR)


def test_initial_temperature():
    t = Temperature(100.0)
    assert t.value == 100.0
    assert not t.clamped


def test_update_decreases_with_rule(meta):
    t = Temperature(100.0)
    t.update(50.0, True, meta)
    assert t.value < 100.0


def test_clamp():
    t = Temperature(100.0)
    t.clamp(50.0, 3)
    assert t.clamped
    assert t.value == 50.0


def test_clamp_prevents_update(meta):
    t = Temperature(100.0)
    t.clamp(50.0)
    t.update(0.0, True, meta)
    assert t.value == 50.0  # Clamped, not updated


def test_tick_clamp_expiration():
    t = Temperature(100.0)
    t.clamp(50.0, 2)
    t.tick_clamp()
    assert t.clamped
    t.tick_clamp()
    assert not t.clamped
