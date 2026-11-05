"""The rational value kind: an exact ``n/m`` in the configuration, read exactly by the engine.

* parsing and refusal of the ``n/m`` text;
* the Metacat Standard Configuration holds the three coefficients as ``Fraction`` values, and
  the engine's arithmetic under them equals the old literals' (bit for bit);
* the configuration hash is stable and tracks the rational;
* the three engine sites follow a non-standard rational (``1/2``).
"""

from __future__ import annotations

import dataclasses
import os
from fractions import Fraction

import pytest

from server.engine.hashing import config_hash
from server.engine.metadata import MetadataProvider
from server.engine.rational import canonical_rational, format_rational, parse_rational
from server.engine.start_check import check_run_start
from server.engine.workspace_objects import WorkspaceObject
from tests.support.run_binding import rebind
from server.services.configuration_input import check_param_value, parse_param_value

SEED = os.path.join(os.path.dirname(__file__), "..", "..", "seed_data")

IMPORTANCE = "enclosed_group_importance_factor"
EDGE = "edge_object_bond_factor"
INTERIOR = "interior_object_bond_factor"


@pytest.fixture(scope="module")
def meta():
    return MetadataProvider.from_standard_configuration(SEED)


def _with(meta, **coefficients):
    return dataclasses.replace(
        meta, formula_coefficients={**meta.formula_coefficients, **coefficients}
    )


# ---- parsing --------------------------------------------------------------


@pytest.mark.parametrize(
    "text, expected",
    [("2/3", Fraction(2, 3)), ("1/6", Fraction(1, 6)), ("4/6", Fraction(2, 3)),
     ("-1/2", Fraction(-1, 2)), ("5/1", Fraction(5)), ("  1/3 ", Fraction(1, 3))],
)
def test_a_rational_parses_exactly(text, expected):
    got = parse_rational(text)
    assert type(got) is Fraction and got == expected


@pytest.mark.parametrize(
    "text", ["", "2", "0.5", "2/0", "2/-3", "1/2/3", "a/b", "1 / 2", "1.5/2", "1/2.5", "½", "2/"],
)
def test_what_is_not_two_integers_over_a_positive_denominator_is_refused(text):
    with pytest.raises(ValueError, match="rational"):
        parse_rational(text)
    assert parse_param_value(text, "rational") == (False, None)
    problem = check_param_value(text, "rational")
    assert problem is not None and "n/m" in problem.message


def test_the_input_check_accepts_a_rational_and_parses_it_exactly():
    assert check_param_value("2/3", "rational") is None
    assert parse_param_value("2/3", "rational") == (True, Fraction(2, 3))


def test_the_canonical_text_is_lowest_terms_with_a_denominator():
    assert canonical_rational("4/6") == "2/3"
    assert canonical_rational("5/1") == "5/1"
    assert format_rational(Fraction(1, 6)) == "1/6"


# ---- the Metacat Standard Configuration -----------------------------------


def test_the_standard_configuration_holds_the_three_as_exact_rationals(meta):
    for name, expected in ((IMPORTANCE, Fraction(2, 3)), (EDGE, Fraction(1, 3)),
                           (INTERIOR, Fraction(1, 6))):
        value = meta.get_formula_coeff(name)
        assert type(value) is Fraction and value == expected, name


def test_the_correctly_rounded_double_is_the_old_literal(meta):
    assert float(meta.get_formula_coeff(IMPORTANCE)) == 2.0 / 3.0


def test_the_three_are_on_the_declared_read_list(meta):
    from server.engine.start_check import REQUIRED_FORMULA_COEFFICIENTS

    listed = {name for name, _ in REQUIRED_FORMULA_COEFFICIENTS}
    assert {IMPORTANCE, EDGE, INTERIOR} <= listed
    for name in (IMPORTANCE, EDGE, INTERIOR):
        lacking = dataclasses.replace(
            meta,
            formula_coefficients={k: v for k, v in meta.formula_coefficients.items() if k != name},
        )
        assert any(p.name == name for p in check_run_start(lacking))


# ---- the hash -------------------------------------------------------------


def test_the_hash_is_stable_and_follows_the_rational(meta):
    again = MetadataProvider.from_standard_configuration(SEED)
    assert config_hash(again) == config_hash(meta)
    assert config_hash(_with(meta, **{IMPORTANCE: Fraction(1, 2)})) != config_hash(meta)
    # The same value, written another way, is the same configuration.
    assert config_hash(_with(meta, **{IMPORTANCE: parse_rational("4/6")})) == config_hash(meta)
    # A rational is not the float that rounds it.
    assert config_hash(_with(meta, **{IMPORTANCE: 2.0 / 3.0})) != config_hash(meta)


# ---- the engine sites -----------------------------------------------------


class _Desc:
    def __init__(self, activation):
        self.descriptor_activation = activation


class _Bond:
    def __init__(self, strength):
        self.strength = strength


class _String:
    length = 5


def _enclosed_object(activation=100.0):
    obj = WorkspaceObject(string=None, left_pos=0, right_pos=0)
    obj.enclosing_group = WorkspaceObject(string=None, left_pos=0, right_pos=1)
    obj.get_relevant_descriptions = lambda: [_Desc(activation)]
    obj.descriptions = [_Desc(activation)]
    return obj


def test_update_importance_under_the_standard_rational_is_the_old_double():
    obj = _enclosed_object(100.0)
    obj.update_importance()
    assert obj.raw_importance == 100.0 * (2.0 / 3.0)


def test_update_importance_follows_a_non_standard_rational(meta):
    rebind(_with(meta, **{IMPORTANCE: Fraction(1, 2)}))
    obj = _enclosed_object(100.0)
    obj.update_importance()
    assert obj.raw_importance == 50.0


def test_the_exact_importance_paths_follow_the_rational(meta, monkeypatch):
    monkeypatch.setattr("server.engine.workspace_objects._description_is_relevant", lambda d: True)
    obj = _enclosed_object(90.0)
    obj.descriptions = [_Desc(90.0)]
    assert obj.exact_raw_importance() == Fraction(90) * Fraction(2, 3)
    n, d = obj.exact_raw_ratio()
    assert Fraction(n, d) == Fraction(60)
    rebind(_with(meta, **{IMPORTANCE: Fraction(1, 2)}))
    assert obj.exact_raw_importance() == Fraction(45)
    n, d = obj.exact_raw_ratio()
    assert Fraction(n, d) == Fraction(45)


def _edge_object():
    obj = WorkspaceObject(string=_String(), left_pos=0, right_pos=0)
    obj.right_bond = _Bond(60)
    return obj


def _interior_object():
    obj = WorkspaceObject(string=_String(), left_pos=2, right_pos=2)
    obj.left_bond = _Bond(60)
    obj.right_bond = _Bond(60)
    return obj


def test_unhappiness_under_the_standard_rationals_is_the_old_division():
    obj = _edge_object()
    obj.update_intra_string_unhappiness()
    assert obj.intra_string_unhappiness == 100.0 - round(60 / 3)
    obj = _interior_object()
    obj.update_intra_string_unhappiness()
    assert obj.intra_string_unhappiness == 100.0 - round(120 / 6)


def test_unhappiness_follows_non_standard_rationals(meta):
    rebind(_with(meta, **{EDGE: Fraction(1, 2), INTERIOR: Fraction(1, 4)}))
    obj = _edge_object()
    obj.update_intra_string_unhappiness()
    assert obj.intra_string_unhappiness == 100.0 - 30
    obj = _interior_object()
    obj.update_intra_string_unhappiness()
    assert obj.intra_string_unhappiness == 100.0 - 30
    rebind(_with(meta, **{EDGE: Fraction(2, 3)}))
    obj = _edge_object()
    obj.update_intra_string_unhappiness()
    assert obj.intra_string_unhappiness == 100.0 - round(60 * 2 / 3)
