"""Tests for temperature-dependent math formulas."""

import os
import pytest
from server.engine.formulas import (
    temp_adjusted_probability,
    temp_adjusted_values,
    update_temperature,
    weighted_average,
    sigmoid,
    make_probability_distribution,
    sample_distribution,
    current_translation_temperature_threshold,
    ProbabilityDistribution,
    VERY_LOW_TRANSLATION_TEMP_DIST,
    LOW_TRANSLATION_TEMP_DIST,
    MEDIUM_TRANSLATION_TEMP_DIST,
    HIGH_TRANSLATION_TEMP_DIST,
    VERY_HIGH_TRANSLATION_TEMP_DIST,
)
from server.engine.metadata import MetadataProvider
from server.engine.rng import RNG
from server.engine.slipnet import Slipnet


SEED_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "seed_data")


@pytest.fixture
def meta():
    return MetadataProvider.from_seed_data(SEED_DIR)


@pytest.fixture
def slipnet(meta):
    return Slipnet.from_metadata(meta)


def test_temp_adjusted_probability_zero(meta):
    assert temp_adjusted_probability(0.0, 50.0, meta) == 0.0


def test_temp_adjusted_probability_one(meta):
    assert temp_adjusted_probability(1.0, 50.0, meta) == 1.0


def test_temp_adjusted_probability_high_temp_pushes_toward_half(meta):
    """At high temperature, probabilities should move toward 0.5."""
    low_prob = temp_adjusted_probability(0.1, 100.0, meta)
    assert low_prob > 0.1  # Pushed up toward 0.5

    high_prob = temp_adjusted_probability(0.9, 100.0, meta)
    assert high_prob < 0.9  # Pushed down toward 0.5


def test_temp_adjusted_probability_low_temp_preserves(meta):
    """At low temperature, probabilities should be close to original."""
    result = temp_adjusted_probability(0.8, 0.0, meta)
    assert abs(result - 0.8) < 0.15  # Should be close to 0.8


def test_temp_adjusted_values_low_temp_increases(meta):
    """At low temperature, exponent is high, amplifying differences."""
    values = [10.0, 50.0, 90.0]
    adjusted = temp_adjusted_values(values, 0.0, meta)
    # Exponent = (100-0)/30 + 0.5 = 3.83
    # High values get much bigger relative to low values
    assert adjusted[2] > adjusted[1] > adjusted[0]


def test_temp_adjusted_values_high_temp_flattens(meta):
    """At high temperature, exponent is low, flattening differences."""
    values = [10.0, 50.0, 90.0]
    adjusted = temp_adjusted_values(values, 100.0, meta)
    # Exponent = (100-100)/30 + 0.5 = 0.5 (square root)
    ratio_original = 90.0 / 10.0  # 9.0
    ratio_adjusted = adjusted[2] / max(adjusted[0], 1)  # Should be < 9
    assert ratio_adjusted < ratio_original


def test_update_temperature_no_rule(meta):
    """Without a supported rule, rule factor = 100, raising temperature."""
    temp = update_temperature(50.0, False, meta)
    # weighted_average([50, 100], [70, 30]) = (50*70 + 100*30) / 100 = 65
    assert temp == 65


def test_update_temperature_with_rule(meta):
    """With a supported rule, rule factor = 0, lowering temperature."""
    temp = update_temperature(50.0, True, meta)
    # weighted_average([50, 0], [70, 30]) = (50*70 + 0*30) / 100 = 35
    assert temp == 35


def test_weighted_average():
    assert weighted_average([10, 20], [1, 1]) == 15.0
    assert weighted_average([10, 20], [3, 1]) == 12.5
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


class TestCurrentTranslationTemperatureThreshold:
    """Test the main function that ties workspace state to threshold sampling."""

    def _make_workspace(self, slipnet, initial="abc", modified="abd", target="xyz"):
        """Create a minimal workspace for testing."""
        from server.engine.workspace import Workspace
        ws = Workspace(initial, modified, target, None, slipnet)
        return ws

    def test_returns_valid_threshold(self, meta, slipnet):
        ws = self._make_workspace(slipnet)
        rng = RNG(42)
        threshold = current_translation_temperature_threshold(ws, rng, meta)
        assert threshold in range(10, 101, 10)

    def test_deterministic_with_same_seed(self, meta, slipnet):
        ws = self._make_workspace(slipnet)
        t1 = current_translation_temperature_threshold(ws, RNG(42), meta)
        t2 = current_translation_temperature_threshold(ws, RNG(42), meta)
        assert t1 == t2

    def test_all_single_letter_strings_gives_very_low_dist(self, meta, slipnet):
        """When all strings are length 1, bond density = 1.0 -> very-low dist.
        The very-low distribution peaks at value 20."""
        ws = self._make_workspace(slipnet, "a", "b", "c")
        results = [current_translation_temperature_threshold(ws, RNG(i), meta)
                   for i in range(200)]
        count_20 = results.count(20)
        # Very-low dist has peak at 20 (freq 150/168 ~ 89%)
        assert count_20 > 100

    def test_no_bonds_gives_very_high_dist(self, meta, slipnet):
        """With no bonds and multi-letter strings, density = 0 -> very-high dist.
        The very-high distribution peaks at value 60."""
        ws = self._make_workspace(slipnet, "abc", "abd", "xyz")
        # No bonds built yet, so density = 0 / 6 = 0
        results = [current_translation_temperature_threshold(ws, RNG(i), meta)
                   for i in range(200)]
        count_60 = results.count(60)
        # Very-high dist has peak at 60 (freq 150/168 ~ 89%)
        assert count_60 > 100

    def test_works_without_meta(self, slipnet):
        """Should work with meta=None using hardcoded defaults."""
        ws = self._make_workspace(slipnet)
        rng = RNG(42)
        threshold = current_translation_temperature_threshold(ws, rng)
        assert threshold in range(10, 101, 10)
