"""Temperature updating against the coefficients in ``seed_data/``."""

import os
import pytest
from server.engine.temperature import Temperature
from server.engine.metadata import MetadataProvider


SEED_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "seed_data")


@pytest.fixture
def meta():
    return MetadataProvider.from_seed_data(SEED_DIR)


# Computes a real temperature through the numeric seam, so it runs once per
# backend in the matrix.
@pytest.mark.numeric_matrix
def test_update_decreases_with_rule(meta):
    t = Temperature(100.0)
    t.update(50.0, True, meta)
    assert t.value < 100.0


def test_clamp_prevents_update(meta):
    t = Temperature(100.0)
    t.clamp(50.0)
    t.update(0.0, True, meta)
    assert t.value == 50.0  # Clamped, not updated
