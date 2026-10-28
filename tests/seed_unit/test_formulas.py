"""The temperature-dependent formulas, against the coefficients in ``seed_data/``."""

import os
import pytest
from server.engine.formulas import (
    temp_adjusted_probability,
    temp_adjusted_values,
    update_temperature,
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
