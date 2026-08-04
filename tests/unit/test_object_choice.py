"""Weighted object choice: the temperature exponent, and the absence of floors.

Every object selection in MetaCat goes through ``choose-object``
(``workspace.ss:499-502``, ``workspace-strings.ss:340-343``)::

    (stochastic-pick objects (temp-adjusted-values weights))

so two things are being tested here.  ``temp-adjusted-values``
(``formulas.ss:32-35``) raises each weight to ``(100 - T)/30 + 0.5`` and rounds,
which sharpens attention as the run cools.  And ``stochastic-pick``
(``utilities.ss:443-448``) gives a weight-0 candidate probability exactly 0,
falling back to a uniform pick only when *every* weight is 0 — so no floor may
be applied to a selection weight anywhere.

The metadata provider is faked down to the two formula coefficients the exponent
reads, and the slipnet down to the ``.nodes`` mapping ``WorkspaceString`` needs
to build its letters.  No database, no seed data, no engine run.
"""

import pytest

from server.engine.rng import RNG
from server.engine.workspace import WorkspaceString, selection_weights


class _FakeMeta:
    """The two formula coefficients ``temp_adjusted_values`` reads."""

    def __init__(self, scale=30.0, base=0.5):
        self._coeffs = {"temp_exponent_scale": scale, "temp_exponent_base": base}

    def get_formula_coeff(self, name):
        return self._coeffs[name]


class _FakeSlipnet:
    """Provides only the ``.nodes`` mapping WorkspaceString reads."""

    def __init__(self):
        self.nodes = {}


def _string_with_salience(saliences, key="intra"):
    """A real ``WorkspaceString`` whose letters carry the given salience values."""
    string = WorkspaceString("ab"[: len(saliences)], _FakeSlipnet(), "initial")
    for letter, value in zip(string.objects, saliences):
        letter.salience[key] = value
    return string


def _frequencies(string, key, temperature, meta, trials=4000):
    rng = RNG(20260803)
    counts = {id(o): 0 for o in string.objects}
    for _ in range(trials):
        counts[id(string.choose_object(key, rng, temperature, meta))] += 1
    return [counts[id(o)] / trials for o in string.objects]


# ---------------------------------------------------------------------------
# The exponent
#
#   exponent(T) = (100 - T)/30 + 0.5
#   exponent(100) = 0.500000   exponent(50) = 2.166667   exponent(0) = 3.833333
#
# Hand-computed for the weight vector [64, 16], with Scheme's `round` applied to
# each adjusted value exactly as `temp-adjusted-values` does:
#
#   T=100  64**0.5      = 8.0            -> 8          16**0.5      = 4.0        -> 4
#          p = 8 / 12 = 0.666667
#   T=50   64**2.166667 = 8192.0         -> 8192       16**2.166667 = 406.0(4)   -> 406
#          p = 8192 / 8598 = 0.952780
#   T=0    64**3.833333 = 8388608.0      -> 8388608    16**3.833333 = 41285.1    -> 41285
#          p = 8388608 / 8429893 = 0.995103
#
# Unadjusted the ratio is 64:16 = 0.8 at every temperature, which is the defect:
# the schedule that turns exploration into exploitation does not exist without
# the exponent.
# ---------------------------------------------------------------------------

EXPONENTIATED = [
    # temperature, expected weights, expected p(first)
    (100.0, [8.0, 4.0], 0.666667),
    (50.0, [8192.0, 406.0], 0.952780),
    (0.0, [8388608.0, 41285.0], 0.995103),
]


@pytest.mark.parametrize("temperature,expected_weights,expected_p", EXPONENTIATED)
def test_selection_weights_are_exponentiated(
    temperature, expected_weights, expected_p
):
    string = _string_with_salience([64.0, 16.0])
    weights = selection_weights(string.objects, "intra", temperature, _FakeMeta())
    assert weights == expected_weights


@pytest.mark.parametrize("temperature,expected_weights,expected_p", EXPONENTIATED)
def test_choice_frequency_tracks_the_exponentiated_distribution(
    temperature, expected_weights, expected_p
):
    string = _string_with_salience([64.0, 16.0])
    salient, dull = _frequencies(string, "intra", temperature, _FakeMeta())
    assert salient == pytest.approx(expected_p, abs=0.02)
    assert dull == pytest.approx(1.0 - expected_p, abs=0.02)


def test_unadjusted_choice_is_flat_at_every_temperature():
    """Omitting temperature/meta is the raw pick the Scheme uses elsewhere.

    ``choose-neighbor`` (``workspace-objects.ss:417-423``) and the top-down
    scouts' string choice (``bonds.ss:221-239``) are bare ``stochastic-pick``s,
    so the raw form has to stay available and has to stay raw.
    """
    string = _string_with_salience([64.0, 16.0])
    assert selection_weights(string.objects, "intra") == [64.0, 16.0]


def test_low_temperature_is_greedier_than_high():
    string = _string_with_salience([64.0, 16.0])
    meta = _FakeMeta()
    hot = _frequencies(string, "intra", 100.0, meta)[0]
    cold = _frequencies(string, "intra", 0.0, meta)[0]
    assert cold > hot


# ---------------------------------------------------------------------------
# No floors — utilities.ss:443-448
# ---------------------------------------------------------------------------

def test_zero_salience_object_is_never_chosen():
    """A weight of 0 is probability 0, not 0.1's worth of a chance."""
    string = _string_with_salience([0.0, 30.0])
    zero, positive = string.objects
    rng = RNG(7)
    for _ in range(500):
        assert string.choose_object("intra", rng, 50.0, _FakeMeta()) is positive


def test_zero_salience_object_is_never_chosen_unadjusted():
    """Also without the exponent, since ``_object_weight`` carried the floor."""
    string = _string_with_salience([0.0, 30.0])
    _, positive = string.objects
    rng = RNG(7)
    for _ in range(500):
        assert string.choose_object("intra", rng) is positive


def test_all_zero_weights_fall_back_to_a_uniform_pick():
    """``stochastic-pick``'s only fallback: ``(if (zero? weight-sum) (random-pick l))``."""
    string = _string_with_salience([0.0, 0.0])
    rng = RNG(11)
    chosen = {
        id(string.choose_object("intra", rng, 50.0, _FakeMeta())) for _ in range(200)
    }
    assert chosen == {id(o) for o in string.objects}


def test_relative_importance_of_zero_is_also_zero_weight():
    """The attribute branch of ``_object_weight`` had its own floor.

    ``important-object-bridge-scout`` (``bridges.ss:984``) picks object1 by
    relative importance, and an object of no importance is not a candidate.
    """
    string = WorkspaceString("ab", _FakeSlipnet(), "initial")
    dull, important = string.objects
    dull.relative_importance = 0.0
    important.relative_importance = 40.0
    assert selection_weights(string.objects, "relative_importance") == [0.0, 40.0]
    rng = RNG(3)
    for _ in range(500):
        assert (
            string.choose_object("relative_importance", rng, 50.0, _FakeMeta())
            is important
        )
