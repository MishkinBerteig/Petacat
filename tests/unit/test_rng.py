"""Tests for the deterministic RNG wrapper."""

from server.engine.rng import RNG


def test_deterministic_same_seed():
    """Same seed produces same sequence."""
    rng1 = RNG(42)
    rng2 = RNG(42)
    for _ in range(100):
        assert rng1.random() == rng2.random()


def test_deterministic_different_seed():
    """Different seeds produce different sequences."""
    rng1 = RNG(42)
    rng2 = RNG(99)
    results1 = [rng1.random() for _ in range(10)]
    results2 = [rng2.random() for _ in range(10)]
    assert results1 != results2


def test_randint_range():
    rng = RNG(1)
    for _ in range(100):
        val = rng.randint(10)
        assert 0 <= val < 10


def test_prob_always():
    rng = RNG(1)
    assert rng.prob(1.0) is True
    assert rng.prob(0.0) is False


def test_prob_statistical():
    rng = RNG(42)
    count = sum(rng.prob(0.5) for _ in range(1000))
    assert 400 < count < 600  # Should be ~500


def test_pick():
    rng = RNG(1)
    items = [1, 2, 3, 4, 5]
    picked = {rng.pick(items) for _ in range(100)}
    assert len(picked) > 1  # Should pick more than one distinct item


def test_weighted_pick():
    rng = RNG(42)
    items = ["a", "b"]
    weights = [100.0, 0.0]
    # Should always pick "a" with weight 100 vs 0
    for _ in range(100):
        assert rng.weighted_pick(items, weights) == "a"


def test_weighted_pick_distribution():
    rng = RNG(42)
    items = ["a", "b"]
    weights = [90.0, 10.0]
    counts = {"a": 0, "b": 0}
    for _ in range(1000):
        counts[rng.weighted_pick(items, weights)] += 1
    assert counts["a"] > counts["b"]
    assert counts["b"] > 0


def test_perturb():
    rng = RNG(42)
    n = 100.0
    results = [rng.perturb(n) for _ in range(100)]
    assert min(results) < n
    assert max(results) > n


def test_stochastic_filter():
    rng = RNG(42)
    items = list(range(100))
    filtered = rng.stochastic_filter(items, lambda _: 0.5)
    assert 30 < len(filtered) < 70


def test_call_count():
    rng = RNG(1)
    assert rng.call_count == 0
    rng.random()
    assert rng.call_count == 1
    rng.randint(10)
    assert rng.call_count == 2


def test_state_save_restore():
    rng = RNG(42)
    # Generate some values
    for _ in range(50):
        rng.random()
    # Save state
    state = rng.get_state()
    # Generate more values
    vals_after_save = [rng.random() for _ in range(20)]
    # Restore state
    rng.set_state(state)
    # Should reproduce the same values
    vals_after_restore = [rng.random() for _ in range(20)]
    assert vals_after_save == vals_after_restore
