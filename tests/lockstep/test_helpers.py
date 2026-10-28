"""Helper conformance (spec §10.2): can each Petacat helper give exactly the results
Metacat's helper gives for the same input, with the same probabilities?

Draw counts are not compared.  Each test scripts the generator underneath ``RNG`` so
the draw is chosen by the test, and checks the result Metacat's definition
(``utilities.ss:461-529``) gives for that draw.
"""

from __future__ import annotations

import pytest

from server.engine.rng import RNG

pytestmark = pytest.mark.lockstep


class _Script:
    """Stands in for ``random.Random``: hands out scripted draws in order."""

    def __init__(self, floats=(), ints=()):
        self.floats = list(floats)
        self.ints = list(ints)

    def random(self):
        return self.floats.pop(0)

    def randrange(self, n):
        value = self.ints.pop(0)
        assert 0 <= value < n, f"scripted {value} is outside range({n})"
        return value


def scripted(floats=(), ints=()) -> RNG:
    rng = RNG(1)
    rng._rng = _Script(floats, ints)
    return rng


# -- prob? -----------------------------------------------------------------------
# (define prob? (lambda (p) (cond ((<= p 0.0) #f) ((>= p 1.0) #t)
#                                 (else (> p (random 1.0))))))


def test_prob_cut_offs_at_zero_and_one_draw_nothing():
    rng = scripted()  # any draw would raise IndexError
    assert rng.prob(0.0) is False and rng.prob(-0.5) is False
    assert rng.prob(1.0) is True and rng.prob(1.5) is True


@pytest.mark.parametrize("draw, expected", [(0.0, True), (0.299, True), (0.3, False), (0.9, False)])
def test_prob_is_true_exactly_when_p_exceeds_the_draw(draw, expected):
    assert scripted(floats=[draw]).prob(0.3) is expected


# -- ~ -----------------------------------------------------------------------------
# (define ~ (lambda (n) (let ((delta (random (add1 (round (sqrt n))))))
#                          (if (prob? 0.5) (+ n delta) (- n delta)))))
# with Metacat's round returning an exact integer (utilities.ss:250-252).


@pytest.mark.parametrize("n, bound", [(2, 2), (4, 3), (3, 3), (9, 4), (2.25, 3), (6.25, 3)])
def test_perturb_draws_a_whole_number_below_one_plus_round_sqrt(n, bound):
    for delta in range(bound):
        # the sign coin: 0.1 < 0.5 is the "+" branch, 0.9 the "-" branch
        assert scripted(floats=[0.1], ints=[delta]).perturb(n) == n + delta
        assert scripted(floats=[0.9], ints=[delta]).perturb(n) == n - delta


def test_perturb_never_draws_a_continuous_delta():
    rng = RNG(5)
    for n in (2, 3, 5, 7, 11, 0.5 + 2):
        assert all(float(rng.perturb(n) - n).is_integer() for _ in range(200))


def test_perturb_of_zero_or_less_is_unchanged():
    assert scripted().perturb(0) == 0 and scripted().perturb(-3) == -3


# -- stochastic-pick / weighted-index ---------------------------------------------
# (weighted-index w weights): the first index whose running total EXCEEDS w
# (strict <), so an item of weight 0 can never be picked.


def test_weighted_pick_uses_the_strict_comparison():
    # total 2, draw 0.5 -> w = 1.0: the first weight does not exceed it, the second does.
    assert scripted(floats=[0.5]).weighted_pick(["a", "b"], [1, 1]) == "b"
    assert scripted(floats=[0.49]).weighted_pick(["a", "b"], [1, 1]) == "a"


def test_weighted_pick_never_picks_a_zero_weight_item():
    items, weights = ["a", "b", "c", "d"], [0, 1, 0, 2]
    # w = 0.0 sits exactly on the boundary of the zero-weight first item.
    assert scripted(floats=[0.0]).weighted_pick(items, weights) == "b"
    rng = RNG(3)
    assert {rng.weighted_pick(items, weights) for _ in range(500)} == {"b", "d"}


def test_weighted_pick_probabilities_are_proportional_to_weights():
    rng = RNG(8)
    picks = [rng.weighted_pick(["a", "b"], [1, 3]) for _ in range(4000)]
    assert 0.20 < picks.count("a") / 4000 < 0.30


def test_weighted_pick_falls_back_to_a_uniform_pick_when_weights_sum_to_zero():
    # random-pick: (random (length l)) -- no float draw is made.
    for index, expected in enumerate("abc"):
        assert scripted(ints=[index]).weighted_pick(list("abc"), [0, 0, 0]) == expected


# -- random-pick ----------------------------------------------------------------------


def test_pick_is_uniform_over_the_list():
    for index, expected in enumerate("abc"):
        assert scripted(ints=[index]).pick(list("abc")) == expected


def test_pick_of_an_empty_list_raises():
    with pytest.raises(ValueError):
        RNG(1).pick([])
