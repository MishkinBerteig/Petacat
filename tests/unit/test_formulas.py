"""The temperature-adjusted probability curve, plus the formulas that carry
their own constants: averaging, the sigmoid, and the five
translation-temperature distributions."""

import pytest
from server.engine.formulas import (
    temp_adjusted_probability,
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


class _FakeMeta:
    """The two formula coefficients ``temp_adjusted_probability`` reads,
    supplied by the test rather than by ``seed_data/``."""

    def __init__(self, sqrt_base=100.0, scale=10.0):
        self._coeffs = {
            "low_prob_sqrt_base": sqrt_base,
            "low_prob_scale_factor": scale,
        }

    def get_formula_coeff(self, name):
        return self._coeffs[name]


# ---------------------------------------------------------------------------
# temp_adjusted_probability — formulas.ss:20-29
#
#   (cond
#     ((= prob 0.0) 0.0)
#     ((<= prob 0.5)
#      (let ((lpf (max 1.0 (truncate (abs (log10 prob))))))
#        (min 0.5 (+ prob (* a (- (expt 10 (1- lpf)) prob))))))
#     ((> prob 0.5)
#      (max 0.5 (1- (+ (1- prob) (* a prob))))))
#
# where a = (% (10- (sqrt (100- T)))) = (10 - sqrt(100 - T)) / 100, and Scheme's
# `1-` is *one minus x* (utilities.ss:500), not a decrement.  So the low branch
# interpolates toward 10^(1 - lpf) — one decade above prob — and the high branch
# is 1 - ((1 - prob) + a*prob).
#
#   a(0)   = (10 - sqrt(100)) / 100 = (10 - 10) / 100         = 0
#   a(50)  = (10 - sqrt(50))  / 100 = (10 - 7.0710678) / 100  = 0.0292893218813452
#   a(100) = (10 - sqrt(0))   / 100 = (10 - 0) / 100          = 0.1
#
# a(0) = 0 makes every T=0 row the identity, which is the whole point of the
# formula: at temperature 0 the caller's probability is used as given.
#
# Hand-computed rows (lpf = max(1, floor(|log10 prob|)); Scheme's `truncate` and
# Python's `floor` agree because |log10 prob| >= 0):
#
#   prob 1e-8   lpf 8, target 10^-7 = 1e-7
#     T=50    1e-8 + 0.0292893218813452*(1e-7 - 1e-8)
#           = 1e-8 + 0.0292893218813452*9e-8 = 1e-8 + 2.636038969e-9 = 1.2636038969e-8
#     T=100   1e-8 + 0.1*9e-8 = 1e-8 + 9e-9  = 1.9e-8
#
#   prob 5e-4   |log10| = 3.30103 -> lpf 3, target 10^-2 = 0.01
#     T=50    0.0005 + 0.0292893218813452*(0.01 - 0.0005)
#           = 0.0005 + 0.0292893218813452*0.0095 = 0.0005 + 0.000278248557873 = 0.000778248557873
#     T=100   0.0005 + 0.1*0.0095 = 0.0005 + 0.00095 = 0.00145
#
#   prob 5e-3   |log10| = 2.30103 -> lpf 2, target 10^-1 = 0.1
#     T=50    0.005 + 0.0292893218813452*(0.1 - 0.005)
#           = 0.005 + 0.0292893218813452*0.095 = 0.005 + 0.002782485578728 = 0.007782485578728
#     T=100   0.005 + 0.1*0.095 = 0.005 + 0.0095 = 0.0145
#
#   prob 0.05   |log10| = 1.30103 -> lpf 1, target 10^0 = 1
#     T=50    0.05 + 0.0292893218813452*(1 - 0.05)
#           = 0.05 + 0.0292893218813452*0.95 = 0.05 + 0.027824855787278 = 0.077824855787278
#     T=100   0.05 + 0.1*0.95 = 0.05 + 0.095 = 0.145   (below the 0.5 clamp)
#
#   prob 0.5    low branch (Scheme's <=); lpf = max(1, floor(0.30103)) = 1, target 1
#     T=50    min(0.5, 0.5 + 0.0292893218813452*0.5) = min(0.5, 0.51464...) = 0.5
#     T=100   min(0.5, 0.5 + 0.1*0.5) = min(0.5, 0.55) = 0.5   (clamped)
#
#   prob 0.9    high branch: 1 - (0.1 + a*0.9) = 0.9 - 0.9a
#     T=50    0.9 - 0.9*0.0292893218813452 = 0.9 - 0.026360389693 = 0.873639610307
#     T=100   0.9 - 0.9*0.1 = 0.9 - 0.09 = 0.81
#
#   prob 1.0    high branch, NO special case: 1 - (0 + a*1) = 1 - a
#     T=50    1 - 0.0292893218813452 = 0.9707106781186548
#     T=100   1 - 0.1 = 0.9
#
# Note that nothing here reaches 0.5 by the low branch except prob 0.5 itself:
# a small probability climbs one decade, it does not become a coin flip.
# ---------------------------------------------------------------------------

_TEMP_ADJUSTED_TABLE = [
    # (prob, temperature, expected)
    (1e-8, 0.0, 1e-8),
    (1e-8, 50.0, 1.2636038969321073e-08),
    (1e-8, 100.0, 1.9e-08),
    (5e-4, 0.0, 5e-4),
    (5e-4, 50.0, 0.0007782485578727798),
    (5e-4, 100.0, 0.00145),
    (5e-3, 0.0, 5e-3),
    (5e-3, 50.0, 0.007782485578727798),
    (5e-3, 100.0, 0.0145),
    (0.05, 0.0, 0.05),
    (0.05, 50.0, 0.07782485578727798),
    (0.05, 100.0, 0.145),
    (0.5, 0.0, 0.5),
    (0.5, 50.0, 0.5),
    (0.5, 100.0, 0.5),
    (0.9, 0.0, 0.9),
    (0.9, 50.0, 0.8736396103067893),
    (0.9, 100.0, 0.81),
    (1.0, 0.0, 1.0),
    (1.0, 50.0, 0.9707106781186548),
    (1.0, 100.0, 0.9),
]


@pytest.mark.parametrize("prob,temperature,expected", _TEMP_ADJUSTED_TABLE)
def test_temp_adjusted_probability_matches_scheme(prob, temperature, expected):
    result = temp_adjusted_probability(prob, temperature, _FakeMeta())
    assert result == pytest.approx(expected, rel=1e-12)


def test_temp_adjusted_probability_zero_short_circuits():
    """``(= prob 0.0) -> 0.0`` is the one special case the Scheme does have;
    without it ``log10(0)`` would be undefined."""
    assert temp_adjusted_probability(0.0, 100.0, _FakeMeta()) == 0.0


def test_temp_adjusted_probability_one_is_not_certain_at_high_temperature():
    """The Scheme has no ``prob = 1.0`` shortcut: certainty is worth at most
    ``1 - adjustment``, so even a strength-100 structure can fail to pass."""
    assert temp_adjusted_probability(1.0, 100.0, _FakeMeta()) < 1.0


def test_temp_adjusted_probability_keeps_a_tiny_probability_tiny():
    """The regression the ``10^(lpf - 1)`` sign error caused: a probability of
    7.5e-9 (a cold 3-group's length description) must not become ~0.5."""
    assert temp_adjusted_probability(7.5e-9, 100.0, _FakeMeta()) < 1e-7


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
