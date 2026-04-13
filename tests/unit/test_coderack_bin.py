"""Tests for Coderack."""

import os
import pytest
from server.engine.coderack import Codelet, Coderack, CoderackBin
from server.engine.metadata import MetadataProvider
from server.engine.rng import RNG


SEED_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "seed_data")


@pytest.fixture
def meta():
    return MetadataProvider.from_seed_data(SEED_DIR)


@pytest.fixture
def coderack(meta):
    return Coderack(meta)


def test_coderack_empty(coderack):
    assert coderack.is_empty
    assert coderack.total_count == 0


def test_post_codelet(coderack):
    c = Codelet("bottom-up-bond-scout", 35)
    coderack.post(c)
    assert coderack.total_count == 1
    assert not coderack.is_empty


def test_choose_and_remove(coderack):
    rng = RNG(42)
    for i in range(10):
        coderack.post(Codelet("test-codelet", 50, time_stamp=i))
    assert coderack.total_count == 10
    c = coderack.choose_and_remove(50.0, rng)
    assert c is not None
    assert coderack.total_count == 9


def test_choose_empty_returns_none(coderack):
    rng = RNG(42)
    result = coderack.choose_and_remove(50.0, rng)
    assert result is None


def test_urgency_to_bin(coderack):
    # Low urgency -> low bin, high urgency -> high bin
    assert coderack._urgency_to_bin(7) == 0
    assert coderack._urgency_to_bin(91) == 6


def test_high_urgency_preferred_at_low_temp(coderack):
    """At low temperature, high-urgency codelets should be preferred."""
    rng = RNG(42)
    for _ in range(20):
        coderack.post(Codelet("low-urg", 7))
        coderack.post(Codelet("high-urg", 91))
    counts = {"low-urg": 0, "high-urg": 0}
    for _ in range(40):
        c = coderack.choose_and_remove(0.0, rng)  # Low temperature
        if c:
            counts[c.codelet_type] += 1
    assert counts["high-urg"] >= counts["low-urg"]


def test_clamp_pattern(coderack):
    pattern = [("bottom-up-bond-scout", 91), ("bond-evaluator", 91)]
    coderack.clamp_pattern(pattern)
    c = Codelet("bottom-up-bond-scout", 35)
    coderack.post(c)
    assert c.urgency == 91  # Clamped up


def test_clear(coderack):
    for _ in range(10):
        coderack.post(Codelet("test", 50))
    coderack.clear()
    assert coderack.is_empty


def test_codelet_type_counts(coderack):
    coderack.post(Codelet("type-a", 50))
    coderack.post(Codelet("type-a", 50))
    coderack.post(Codelet("type-b", 50))
    counts = coderack.get_codelet_type_counts()
    assert counts["type-a"] == 2
    assert counts["type-b"] == 1
