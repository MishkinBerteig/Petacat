"""Shared test fixtures.

All tests are deterministic: every stochastic operation uses a fixed seed.
The RNG is the single source of randomness, and identical seeds produce
identical behavior regardless of execution environment.
"""

import os
import sys
import asyncio
import pytest

# Ensure the project root is on the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

SEED_DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "seed_data")

# Fixed seed for all deterministic tests
DETERMINISTIC_SEED = 42


@pytest.fixture
def seed_data_dir():
    return SEED_DATA_DIR


@pytest.fixture
def deterministic_seed():
    """Fixed seed ensuring all stochastic tests are reproducible."""
    return DETERMINISTIC_SEED
