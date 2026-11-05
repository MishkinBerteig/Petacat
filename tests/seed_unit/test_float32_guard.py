"""The GPU exactness guard: a float32 backend runs only configurations it can run exactly.

The conditions are measured in ``agents-workspace/metacat-cleanup/round2/S3-dead-open/``
(``measure_guard*.py``); these tests pin the decisions, not the arithmetic.
"""

import dataclasses

import pytest

from server.engine.numeric import available_backends, get_backend
from server.engine.numeric.backend import (
    InexactConfiguration,
    exact_backend_for,
    float32_exactness_problem,
    use_backend,
)
from tests.support.standard_configuration import standard_activation

needs_gpu = pytest.mark.skipif("mlx" not in available_backends(), reason="no GPU backend")


def _act(**kw):
    return dataclasses.replace(standard_activation(), **kw)


def test_standard_is_exact():
    assert float32_exactness_problem(standard_activation(), 1.0) is None


@pytest.mark.parametrize("kw", [{"max_activation": 120.0}, {"max_activation": 100.5},
                                {"max_activation": 1048576.0},
                                {"full_activation_threshold": 49.9},
                                {"full_activation_threshold": 60.0}])
def test_values_the_measurement_found_exact_are_not_refused(kw):
    assert float32_exactness_problem(_act(**kw), 1.0) is None


@pytest.mark.parametrize("kw, word", [({"max_activation": 100.1}, "max_activation"),
                                      ({"max_activation": 1500000.0}, "max_activation"),
                                      ({"full_activation_threshold": 50.00000001},
                                       "full_activation_threshold")])
def test_values_the_measurement_found_inexact_are_refused_naming_the_value(kw, word):
    assert word in float32_exactness_problem(_act(**kw), 1.0)


def test_an_inexact_spread_scale_is_refused_and_an_exact_one_is_not():
    assert float32_exactness_problem(standard_activation(), 5 / 15) is not None
    assert "spread scale" in float32_exactness_problem(standard_activation(), 25 / 15)
    assert float32_exactness_problem(standard_activation(), 0.5) is None
    assert float32_exactness_problem(standard_activation(), 2.0) is None


def test_a_float64_backend_is_never_refused():
    numpy_backend = get_backend("numpy")
    assert exact_backend_for(numpy_backend, _act(max_activation=100.1), 1 / 3) is numpy_backend


@needs_gpu
def test_auto_falls_back_to_a_float64_backend_and_an_explicit_gpu_raises():
    gpu = get_backend("mlx")
    with use_backend("auto"):
        chosen = exact_backend_for(gpu, _act(max_activation=100.1), 1.0)
        assert chosen.exact
        assert exact_backend_for(gpu, standard_activation(), 1.0) is gpu
    with use_backend("mlx"):
        with pytest.raises(InexactConfiguration, match="max_activation=100.1"):
            exact_backend_for(gpu, _act(max_activation=100.1), 1.0)
