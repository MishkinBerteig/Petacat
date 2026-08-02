"""The formulas that carry their own constants: averaging, the sigmoid, and the
five translation-temperature distributions."""

import pytest
from server.engine.formulas import (
    weighted_average,
    sigmoid,
    make_probability_distribution,
    sample_distribution,
    ProbabilityDistribution,
    VERY_LOW_TRANSLATION_TEMP_DIST,
    LOW_TRANSLATION_TEMP_DIST,
    MEDIUM_TRANSLATION_TEMP_DIST,
    HIGH_TRANSLATION_TEMP_DIST,
    VERY_HIGH_TRANSLATION_TEMP_DIST,
)
from server.engine.rng import RNG


def test_weighted_average_equal_weights():
    assert weighted_average([10, 20], [1, 1]) == 15.0


def test_weighted_average_unequal_weights():
    assert weighted_average([10, 20], [3, 1]) == 12.5


def test_weighted_average_empty_is_zero():
    assert weighted_average([], []) == 0.0


def test_sigmoid_midpoint():
    """At midpoint, sigmoid should be ~0.5."""
    result = sigmoid(40.0, 3.0, 40.0)
    assert abs(result - 0.5) < 0.01


def test_sigmoid_monotonic():
    """Sigmoid should be monotonically increasing."""
    prev = 0.0
    for x in range(0, 101, 5):
        val = sigmoid(float(x), 3.0, 50.0)
        assert val >= prev
        prev = val


# ---------------------------------------------------------------------------
# Translation temperature threshold distribution tests
# ---------------------------------------------------------------------------


class TestMakeProbabilityDistribution:
    def test_creates_named_tuple(self):
        dist = make_probability_distribution([10, 20, 30], [1, 2, 3])
        assert isinstance(dist, ProbabilityDistribution)
        assert dist.values == (10, 20, 30)
        assert dist.frequencies == (1, 2, 3)

    def test_immutable(self):
        dist = make_probability_distribution([10, 20], [5, 5])
        with pytest.raises(AttributeError):
            dist.values = (99,)


class TestSampleDistribution:
    def test_returns_valid_value(self):
        dist = make_probability_distribution([10, 20, 30], [1, 1, 1])
        rng = RNG(42)
        for _ in range(50):
            val = sample_distribution(dist, rng)
            assert val in (10, 20, 30)

    def test_deterministic_with_same_seed(self):
        dist = make_probability_distribution([10, 20, 30, 40, 50], [1, 1, 1, 1, 1])
        results_a = [sample_distribution(dist, RNG(99)) for _ in range(1)]
        results_b = [sample_distribution(dist, RNG(99)) for _ in range(1)]
        assert results_a == results_b

    def test_heavily_weighted_value_dominates(self):
        """A value with overwhelmingly high frequency should be chosen most often."""
        dist = make_probability_distribution([10, 20, 30], [1, 1000, 1])
        rng = RNG(7)
        results = [sample_distribution(dist, rng) for _ in range(200)]
        count_20 = results.count(20)
        assert count_20 > 180  # Should be ~199 out of 200


class TestDistributionConstants:
    """Verify the 5 distributions match the Scheme constants."""

    def test_very_low_dist(self):
        assert VERY_LOW_TRANSLATION_TEMP_DIST.values == (10, 20, 30, 40, 50, 60, 70, 80, 90, 100)
        assert VERY_LOW_TRANSLATION_TEMP_DIST.frequencies == (5, 150, 5, 2, 1, 1, 1, 1, 1, 1)

    def test_low_dist(self):
        assert LOW_TRANSLATION_TEMP_DIST.values == (10, 20, 30, 40, 50, 60, 70, 80, 90, 100)
        assert LOW_TRANSLATION_TEMP_DIST.frequencies == (2, 5, 150, 5, 2, 1, 1, 1, 1, 1)

    def test_medium_dist(self):
        assert MEDIUM_TRANSLATION_TEMP_DIST.values == (10, 20, 30, 40, 50, 60, 70, 80, 90, 100)
        assert MEDIUM_TRANSLATION_TEMP_DIST.frequencies == (1, 2, 5, 150, 5, 2, 1, 1, 1, 1)

    def test_high_dist(self):
        assert HIGH_TRANSLATION_TEMP_DIST.values == (10, 20, 30, 40, 50, 60, 70, 80, 90, 100)
        assert HIGH_TRANSLATION_TEMP_DIST.frequencies == (1, 1, 2, 5, 150, 5, 2, 1, 1, 1)

    def test_very_high_dist(self):
        assert VERY_HIGH_TRANSLATION_TEMP_DIST.values == (10, 20, 30, 40, 50, 60, 70, 80, 90, 100)
        assert VERY_HIGH_TRANSLATION_TEMP_DIST.frequencies == (1, 1, 1, 2, 5, 150, 5, 2, 1, 1)

    def test_all_distributions_have_10_values(self):
        for dist in [
            VERY_LOW_TRANSLATION_TEMP_DIST,
            LOW_TRANSLATION_TEMP_DIST,
            MEDIUM_TRANSLATION_TEMP_DIST,
            HIGH_TRANSLATION_TEMP_DIST,
            VERY_HIGH_TRANSLATION_TEMP_DIST,
        ]:
            assert len(dist.values) == 10
            assert len(dist.frequencies) == 10

    def test_peak_shifts_with_bond_density(self):
        """Each distribution's peak frequency should shift to the right
        as bond density decreases (very-low -> very-high)."""
        dists = [
            VERY_LOW_TRANSLATION_TEMP_DIST,
            LOW_TRANSLATION_TEMP_DIST,
            MEDIUM_TRANSLATION_TEMP_DIST,
            HIGH_TRANSLATION_TEMP_DIST,
            VERY_HIGH_TRANSLATION_TEMP_DIST,
        ]
        peak_indices = [d.frequencies.index(150) for d in dists]
        # Peaks should be at indices 1, 2, 3, 4, 5 respectively
        assert peak_indices == [1, 2, 3, 4, 5]
