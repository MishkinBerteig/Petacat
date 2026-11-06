"""Exact rounding where Metacat is exact (``utilities.ss:251``, ``100*`` at ``utilities.ss:544``).

Scheme's whole numbers and the ratios they make stay exact until a float enters, and ``round`` of an
exact ratio is half-to-even on the exact value.  ``server/engine/formulas.py`` rounds through
whole-number arithmetic; these tests compare it with ``fractions.Fraction`` (a test oracle only:
no rational type is used under ``server/``) over every whole input the engine can reach.
"""

from __future__ import annotations

import random
from fractions import Fraction

import pytest

from server.engine import rules as rules_module
from server.engine.concept_mappings import _rounded_depth_product
from server.engine.formulas import ratio_of, round_exact, round_ratio
from server.engine.rules import Rule, rule_quality

pytestmark = pytest.mark.numeric_matrix


def test_round_ratio_is_half_to_even_on_the_exact_value() -> None:
    for numerator in range(-60, 61):
        for denominator in (1, 2, 3, 4, 5, 6, 7, 10, 40, 100, -2, -7):
            assert round_ratio(numerator, denominator) == round(Fraction(numerator, denominator))
    assert [round_ratio(n, 2) for n in (1, 3, 5, 7, -1, -3)] == [0, 2, 2, 4, 0, -2]


def test_ratio_of_is_exact_for_an_int_a_whole_float_and_a_ratio_type() -> None:
    assert ratio_of(75) == (75, 1) and ratio_of(75.0) == (75, 1) and ratio_of(0.75) == (3, 4)
    assert ratio_of(Fraction(37, 50)) == (37, 50)


def test_the_75_74_tie_is_56_and_the_float_product_is_not() -> None:
    assert 100 * (0.75 * 0.74) == pytest.approx(55.5) and round(100 * (0.75 * 0.74)) == 55
    assert round_exact((100, 75, 74), (100, 100)) == 56


class _Bridge:
    def __init__(self, strength: int) -> None:
        self.strength = strength


def _degree(monkeypatch: pytest.MonkeyPatch, strengths: tuple) -> int:
    rule = Rule.__new__(Rule)
    rule.supporting_bridges = [_Bridge(s) for s in strengths]
    monkeypatch.setattr(rules_module, "_get_equivalent_bridge", lambda workspace, b: b)
    return rule.get_degree_of_support(None)


def _oracle_degree(strengths: tuple) -> int:
    product = Fraction(1)
    for s in strengths:
        product *= Fraction(s, 100)
    return round(100 * product)


def test_degree_of_support_equals_the_exact_product_for_every_whole_strength(monkeypatch) -> None:
    assert _degree(monkeypatch, ()) == 100
    for a in range(101):
        assert _degree(monkeypatch, (a,)) == _oracle_degree((a,)) == a
        for b in range(101):
            assert _degree(monkeypatch, (a, b)) == _oracle_degree((a, b)), (a, b)
    rng = random.Random(7)
    for _ in range(20000):
        strengths = tuple(rng.randint(0, 100) for _ in range(rng.randint(3, 6)))
        assert _degree(monkeypatch, strengths) == _oracle_degree(strengths), strengths


def test_concept_mapping_strength_and_slippability_are_exact_for_every_association_and_depth() -> None:
    """``50 * (1 + (30/100)**2)`` is 54.50000000000001 in floats and exactly 54.5 (rounds to 54);
    ``50 * (1 - (90/100)**2)`` is 9.500000000000002 against exactly 9.5 (rounds to 10)."""
    assert _rounded_depth_product(50, 30, 2, 1, 1) == 54
    assert _rounded_depth_product(50, 90, 2, -1, 1) == 10
    for assoc in range(100):
        for depth in range(101):
            assert _rounded_depth_product(assoc, depth, 2, 1, 1) == round(Fraction(assoc) * (1 + Fraction(depth, 100) ** 2))
            assert _rounded_depth_product(assoc, depth, 2, -1, 1) == round(Fraction(assoc) * (1 - Fraction(depth, 100) ** 2))
            assert _rounded_depth_product(assoc, float(depth), 2, 1, 1) == _rounded_depth_product(assoc, depth, 2, 1, 1)


def test_rule_quality_is_exact_for_every_uniformity_abstractness_and_reachable_succinctness() -> None:
    """``0.7 * 45`` is 31.499999999999996; the exact 31.5 rounds to 32 (u=70, a=37, s=57)."""
    assert rule_quality(70, 37, 57, 3, 2) == 32
    succinctness = sorted({100} | {round(Fraction(400, 3 + n)) for n in range(1, 40)})
    for u in range(101):
        for a in range(101):
            for s in succinctness:
                assert rule_quality(u, a, s, 3, 2) == round(Fraction(u, 100) * Fraction(3 * a + 2 * s, 5)), (u, a, s)
    assert rule_quality(55, 10, 10, 0, 0) == 0


def test_the_slipnet_spread_is_exact_for_any_update_cycle_length() -> None:
    """``(* (/ ucl 15) (% assoc) activation)``: with ucl 5, assoc 14, activation 75 the float form gives 3
    where the exact ratio 3.5 gives 4."""
    assert round_exact((5, 14, 75), (15.0, 100)) == 4
    for ucl in range(1, 61):
        for assoc in range(0, 101, 1):
            for activation in range(0, 101, 3):
                assert round_exact((ucl, assoc, activation), (15.0, 100)) == round(
                    Fraction(ucl, 15) * Fraction(assoc, 100) * activation)


def test_a_real_node_spreads_exactly_at_a_non_reference_cycle_length() -> None:
    from tests.unit.test_arithmetic_fidelity import SlipnetLink, make_node

    src = make_node("a", "a", 50)
    dst = make_node("b", "b", 50)
    link = SlipnetLink(src, dst, "lateral", fixed_link_length=86)  # association 14
    src.lateral_links.append(link)
    src.activation = 75
    src.spread_activation_to_neighbors(5)  # 5/15 * 14/100 * 75 = 3.5, which rounds to 4
    assert dst.activation_buffer == 4


def test_a_whole_number_exponent_makes_the_decay_rate_an_exact_ratio() -> None:
    from tests.unit.test_arithmetic_fidelity import make_node

    node = make_node("a", "a", 50)
    node.compute_rate_of_decay(30)  # exponent 2: rate 1 - (50/100)**2 = 3/4
    node.activation = 7
    node.activation_buffer = 0
    node.decay()
    assert node.activation_buffer == -round(Fraction(3, 4) * 7)  # -5.25 -> -5
    node.compute_rate_of_decay(15)
    assert node._decay_exact is None
