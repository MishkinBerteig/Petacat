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


def test_prob_one_is_always_true():
    rng = RNG(1)
    assert rng.prob(1.0) is True


def test_prob_zero_is_always_false():
    rng = RNG(1)
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


def test_perturb_of_a_perfect_square_draws_an_integer_delta():
    """``(~ 4)``: ``(sqrt 4)`` is exact, so ``(random 3)`` yields an integer.

    Scheme: ``utilities.ss:426-429``.  The reachable thresholds are therefore
    exactly ``{2, 3, 4, 5, 6}``.
    """
    rng = RNG(7)
    seen = {rng.perturb(4) for _ in range(400)}
    assert seen == {2.0, 3.0, 4.0, 5.0, 6.0} or seen == {2, 3, 4, 5, 6}
    assert all(float(v).is_integer() for v in seen)


def test_perturb_of_a_non_square_draws_a_continuous_delta():
    """``(~ 2)``: ``(round (sqrt 2))`` is the flonum 1.0, so the delta is real.

    ``(random 2.0)`` returns a flonum in ``[0.0, 2.0)``, giving a threshold
    anywhere in ``(0.0, 4.0)`` rather than one of ``{1, 2, 3}``.
    """
    rng = RNG(7)
    values = [rng.perturb(2) for _ in range(400)]
    assert not all(float(v).is_integer() for v in values)
    assert 0.0 < min(values) and max(values) < 4.0


def test_the_blur_makes_two_objects_few_about_half_the_time():
    """The consequence that makes the flonum reading worth reproducing.

    ``rough-num-of-objects`` (``workspace.ss:683-688``) asks ``(< count (~ 2))``.
    With the continuous delta a count of 2 is ``few`` half the time — it needs
    only ``delta > 0`` on the upward branch.  Under an integer delta it would
    need ``delta = 1``, i.e. a quarter of the time.
    """
    rng = RNG(11)
    few = sum(1 for _ in range(4000) if 2 < rng.perturb(2))
    assert 0.45 < few / 4000 < 0.55
