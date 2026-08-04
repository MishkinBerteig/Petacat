"""The temperature-dependent formulas, against the coefficients in ``seed_data/``."""

import os
import pytest
from server.engine.formulas import (
    temp_adjusted_probability,
    temp_adjusted_values,
    update_temperature,
    current_translation_temperature_threshold,
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
    """1.0 has no special case in the Scheme (formulas.ss:20-29): it takes the
    ``> 0.5`` branch and comes back as ``1 - (10 - sqrt(100 - T)) / 100``.
    At T=50 that is 1 - (10 - sqrt(50)) / 100 = 1 - 0.0292893... = 0.9707107."""
    assert temp_adjusted_probability(1.0, 50.0, meta) == pytest.approx(
        0.9707106781186548
    )


def test_temp_adjusted_probability_one_at_zero_temperature(meta):
    """The adjustment is zero at T=0, so 1.0 survives intact."""
    assert temp_adjusted_probability(1.0, 0.0, meta) == 1.0


def test_temp_adjusted_probability_high_temp_pushes_low_prob_up(meta):
    """At high temperature, a low probability moves up toward 0.5."""
    assert temp_adjusted_probability(0.1, 100.0, meta) > 0.1


def test_temp_adjusted_probability_high_temp_pushes_high_prob_down(meta):
    """At high temperature, a high probability moves down toward 0.5."""
    assert temp_adjusted_probability(0.9, 100.0, meta) < 0.9


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
