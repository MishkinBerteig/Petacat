"""Metacat Mode reads a problem through Metacat's input parser; a Training Mode Session does not.

The rows of ``THE-THREE-SYSTEMS.md``'s table, at the parser (``server/services/input_parser.py``) and at the
request models of the Metacat Mode doors, which no longer refuse text themselves.  The same text
goes to Training Mode's ``ProblemInput`` and is kept exactly.  The end-to-end doors are in
``tests/e2e/test_input_parser_doors.py``.
"""

from __future__ import annotations

import pytest

from server.api.admin import DemoProblemRequest
from server.api.runs import CreateRunRequest
from server.api.swarm import SwarmRequest
from server.api.training_mode_sessions import ProblemInput
from server.services.input_parser import INVALID_INPUT, InvalidInput, read_problem
from tests.support.standard_configuration import standard_meta

META = standard_meta()

#: THE-THREE-SYSTEMS.md's table: input -> (initial, modified, target, answer, seed).
READ = [
    (("abc", "abd", "xyz"), ("abc", "abd", "xyz", None)),
    (("abc", "abd", "xyZ"), ("abc", "abd", "xyz", None)),
    (("ABC", "Abd", "XYZ"), ("abc", "abd", "xyz", None)),
    (("abc", "abd", "x-z"), ("abc", "abd", "x", "z")),
    (("abc", "abd", "x z"), ("abc", "abd", "x", "z")),
    (("abc", "abd", "x😀z"), ("abc", "abd", "x", "z")),
    (("abc", "abd", "x́z"), ("abc", "abd", "x", "z")),
    (("a.b", "abd", "xyz"), ("a", "b", "abd", "xyz")),  # the Initial field alone holds two strings
    (("abc", "abd", "xyz", "wyz"), ("abc", "abd", "xyz", "wyz")),
]
INVALID = [
    ("abc", "abd", "xy1"), ("abc", "abd", "é"), ("abc", "abd", "日本"), ("abc", "abd", "xyz", None, 0),
    ("abc", "abd", "xyz", None, -1), ("abc", "abd", "xyz", None, 4294967296), ("abc", "abd", "xyz", "wy1"),
    ("1", "2", "3"), ("abc", "abd", ""), ("", "abd", "xyz"), ("abc", "abd", "xyz\x00z", "q"),
    ("abc", "abd", "x\ud800z"), ("abc", "abd", "xyz 5 6"), ("abc", "abd", "xyz", "wyz", 0),
]


@pytest.mark.parametrize("fields,expected", READ)
def test_the_fields_are_read_as_one_line(fields, expected):
    p = read_problem(META, *fields, seed=7)
    assert (p.initial, p.modified, p.target, p.answer) == expected
    assert p.seed == 7


@pytest.mark.parametrize("fields", INVALID)
def test_input_the_parser_refuses_says_exactly_invalid_input(fields):
    with pytest.raises(InvalidInput) as exc:
        read_problem(META, *fields)
    assert str(exc.value) == INVALID_INPUT == "Invalid input!"


def test_digits_alone_are_a_seed_in_the_fourth_or_fifth_place_and_invalid_anywhere_else():
    assert read_problem(META, "abc", "abd", "xyz 5").seed == 5
    assert read_problem(META, "abc", "abd", "xyz wyz 5").answer == "wyz"
    for fields in (("5", "abd", "xyz"), ("abc", "5", "xyz"), ("abc", "abd", "5")):
        with pytest.raises(InvalidInput):
            read_problem(META, *fields)


def test_no_seed_gives_a_random_seed_in_range():
    seeds = {read_problem(META, "abc", "abd", "xyz").seed for _ in range(20)}
    assert all(1 <= s <= 4294967295 for s in seeds) and len(seeds) > 1


def test_a_seed_on_the_line_and_a_seed_field_are_two_numbers():
    with pytest.raises(InvalidInput):
        read_problem(META, "abc", "abd", "xyz 5", None, 6)


@pytest.mark.parametrize("model,extra", [(CreateRunRequest, {}), (SwarmRequest, {}), (DemoProblemRequest, {"name": "n"})])
def test_the_metacat_mode_request_models_leave_the_text_to_the_parser(model, extra):
    m = model(initial="ABC", modified="é", target="x-z", answer="1", **extra)
    assert (m.initial, m.modified, m.target, m.answer) == ("ABC", "é", "x-z", "1")


def test_the_same_text_is_kept_exactly_in_training_mode():
    m = ProblemInput(initial="abC", modified="xy1", target="日本", answer="😀é")
    assert (m.initial, m.modified, m.target, m.answer) == ("abC", "xy1", "日本", "😀é")


def test_a_very_long_digit_run_is_invalid_input_not_a_crash():
    """Python will not make an integer of more than 4,300 digits; in Metacat it is a bignum above
    the largest seed, so the line is invalid, in the seed place and in the third place."""
    run = "1" * 5000
    for fields in (("abc", "abd", "xyz " + run), ("abc", "abd", run), ("abc", "abd", "xyz wyz " + run)):
        with pytest.raises(InvalidInput):
            read_problem(META, *fields)
    with pytest.raises(InvalidInput):
        read_problem(META, "abc", "abd", "xyz", None, int(run[:4000]))
