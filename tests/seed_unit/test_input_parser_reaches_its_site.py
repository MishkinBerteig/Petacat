"""Metacat Mode's input parser reads every one of its rules from the configuration.

``server/services/input_parser.py`` has the parser's control flow and nothing that decides what the
parser does.  Each row below changes one row or one value of the Metacat Standard Configuration and
shows that what the parser does changes with it, so a rule that goes back into the code fails here:

* every row of ``input_character_ranges`` (the characters that are letters, and the ones that are digits);
* every row of ``input_lowering_ranges``;
* the ``largest_seed`` engine parameter;
* the Slipnet's glyph nodes, which are the letters a string may be made of;
* a Training Mode Session's own text rules are untouched: ``problem_text`` does not read any of this.

The Standard Configuration is also pinned to Metacat: the readable letters are a to z and the largest
seed is 4294967295.
"""

from __future__ import annotations

import dataclasses

import pytest

from server.engine.metadata import SlipnodeSpec
from server.services.input_parser import (
    InvalidInput, ParserConfigurationError, parse_line, read_problem, rules_from,
)
from tests.support.standard_configuration import standard_meta


def _rules(meta=None):
    return rules_from(meta or standard_meta())


def test_the_standard_configuration_is_metacats():
    meta = standard_meta()
    assert meta.get_param("largest_seed") == 4294967295
    assert isinstance(meta.get_param("largest_seed"), int)
    letters = {s.glyph for s in meta.slipnet_node_specs.values() if s.glyph is not None}
    assert letters == set("abcdefghijklmnopqrstuvwxyz")
    assert _rules().readable == letters


def test_every_character_range_row_decides_what_it_names():
    meta = standard_meta()
    base = _rules(meta)
    wrong = []
    for i, (kind, first, last) in enumerate(meta.input_character_ranges):
        rows = meta.input_character_ranges[:i] + meta.input_character_ranges[i + 1:]
        rules = _rules(dataclasses.replace(meta, input_character_ranges=rows))
        # The lowering is not involved: ask about a character the row names, lowered already.
        for code in {first, last}:
            char = chr(code)
            if rules.is_kind(kind, char) or not base.is_kind(kind, char):
                wrong.append((i, kind, hex(code)))
    assert not wrong, wrong[:10]


def test_every_lowering_row_decides_what_it_names():
    meta = standard_meta()
    base = _rules(meta)
    wrong = []
    for i, (first, last, _step, _delta) in enumerate(meta.input_lowering_ranges):
        rows = meta.input_lowering_ranges[:i] + meta.input_lowering_ranges[i + 1:]
        rules = _rules(dataclasses.replace(meta, input_lowering_ranges=rows))
        for code in {first, last}:
            char = chr(code)
            if rules.lower(char) != char or base.lower(char) == char:
                wrong.append((i, hex(code)))
    assert not wrong, wrong[:10]


def test_a_changed_lowering_row_changes_what_a_line_reads_as():
    meta = standard_meta()
    # Metacat lowers A to Z by 32.  Lowering them by nothing at all makes them unreadable letters.
    rows = tuple(
        (r[0], r[1], r[2], 0) if (r[0], r[1]) == (65, 90) else r
        for r in meta.input_lowering_ranges
    )
    assert parse_line(_rules(meta), "ABC abd xyz").initial == "abc"
    with pytest.raises(InvalidInput):
        parse_line(_rules(dataclasses.replace(meta, input_lowering_ranges=rows)), "ABC abd xyz")


def test_a_changed_character_class_changes_what_separates():
    meta = standard_meta()
    base = _rules(meta)
    assert parse_line(base, "abc abd x-z").answer == "z"
    # A hyphen made a digit: the string x is then followed by a digit, which is invalid.
    extra = ("numeric", 45, 45)
    changed = dataclasses.replace(
        meta, input_character_ranges=meta.input_character_ranges + (extra,))
    with pytest.raises(InvalidInput):
        parse_line(_rules(changed), "abc abd x-z")


def test_the_largest_seed_is_read_from_the_configuration():
    meta = standard_meta()
    read_problem(meta, "abc", "abd", "xyz", None, 4294967295)
    with pytest.raises(InvalidInput):
        read_problem(meta, "abc", "abd", "xyz", None, 4294967296)
    small = dataclasses.replace(meta, params={**meta.params, "largest_seed": 10})
    assert read_problem(small, "abc", "abd", "xyz", None, 10).seed == 10
    with pytest.raises(InvalidInput):
        read_problem(small, "abc", "abd", "xyz", None, 11)
    # A random seed is within the configured largest.
    assert all(1 <= read_problem(small, "abc", "abd", "xyz").seed <= 10 for _ in range(50))


def test_a_configuration_without_the_largest_seed_stops_the_request():
    meta = standard_meta()
    params = {k: v for k, v in meta.params.items() if k != "largest_seed"}
    with pytest.raises(ParserConfigurationError, match="largest_seed"):
        read_problem(dataclasses.replace(meta, params=params), "abc", "abd", "xyz")


def test_a_configuration_without_character_ranges_or_letters_stops_the_request():
    meta = standard_meta()
    with pytest.raises(ParserConfigurationError, match="alphabetic"):
        _rules(dataclasses.replace(meta, input_character_ranges=()))
    no_letters = {
        k: dataclasses.replace(v, glyph=None) for k, v in meta.slipnet_node_specs.items()
    }
    with pytest.raises(ParserConfigurationError, match="letter node"):
        _rules(dataclasses.replace(meta, slipnet_node_specs=no_letters))


def test_removing_a_letter_node_makes_that_letter_unreadable():
    meta = standard_meta()
    specs = dict(meta.slipnet_node_specs)
    specs["plato-z"] = dataclasses.replace(specs["plato-z"], glyph=None)
    changed = dataclasses.replace(meta, slipnet_node_specs=specs)
    assert read_problem(meta, "abc", "abd", "xyz", None, 1).target == "xyz"
    with pytest.raises(InvalidInput):
        read_problem(changed, "abc", "abd", "xyz", None, 1)
    assert read_problem(changed, "abc", "abd", "xyy", None, 1).target == "xyy"


def test_adding_a_letter_node_makes_that_letter_readable_with_no_code_change():
    meta = standard_meta()
    with pytest.raises(InvalidInput):
        read_problem(meta, "abc", "abd", "xyé", None, 1)
    specs = dict(meta.slipnet_node_specs)
    specs["plato-é"] = SlipnodeSpec(
        name="plato-é", short_name="é", conceptual_depth=10, plain_name="é", glyph="é")
    changed = dataclasses.replace(meta, slipnet_node_specs=specs)
    problem = read_problem(changed, "abc", "abd", "xyé", None, 1)
    assert problem.target == "xyé"
    # Upper case is lowered by the same rows: É is read as é.
    assert read_problem(changed, "abc", "abd", "xyÉ", None, 1).target == "xyé"
