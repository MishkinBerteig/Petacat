"""The problem-string check of Training Mode: any Unicode text is valid, and only what the database cannot store is refused.

A Training Mode Session takes this check (``server/services/problem_text.py``); Metacat Mode does not.
Metacat Mode reads every problem through a port of Metacat's input parser instead (lowering case,
splitting on punctuation, refusing a digit inside a string and a letter outside a to z), which
``tests/unit/test_input_parser_doors.py`` and ``tests/lockstep/test_input_parser.py`` hold.  A string may hold any
script, emoji and combining sequences, spaces, tabs, line breaks, punctuation, any case and any length,
and is kept exactly: no trimming, no case change, no normalisation.  Refused, each with a message that
says why: U+0000 (PostgreSQL ``text`` and ``jsonb`` cannot store it) and a lone surrogate (not UTF-8 text).
Every problem keeps the structural rule: initial, modified and target non-empty,
answer null or non-empty.  The Training Mode Session request model (``ProblemInput``) applies the check.
"""

from __future__ import annotations

import unicodedata

import pytest
from pydantic import ValidationError

from server.api.training_mode_sessions import ProblemInput
from server.services.problem_text import (
    ProblemTextError, check_deep, check_problem, check_problem_mapping, check_string,
)

NFC = unicodedata.normalize("NFC", "é")
NFD = unicodedata.normalize("NFD", "é")

CORPUS = [
    "a b", "a,b;c", "x->y", "ABC", "1 2 3", NFC, NFD, "αβγ", "абв", "אבג", "漢字", "नमस्ते",
    "😀", "👨‍👩‍👧", "🇨🇦", "\t", "a\nb", "a\r\nb", "\ufeff", "\u202e", 'say "hi"', "back`tick", "#hash",
    "→", "?", "  padded  ", "x" * 1000, "C:\\dir", " ", "\u2028", "\U0010ffff",
]


def test_the_two_spellings_of_e_acute_really_differ():
    assert NFC != NFD and len(NFC) == 1 and len(NFD) == 2


@pytest.mark.parametrize("s", CORPUS)
def test_every_corpus_string_is_accepted_in_every_field(s):
    check_string("initial", s)
    check_problem(s, s, s, s)
    check_problem(s, s, s, s, require_nonempty=True)
    check_problem_mapping({"initial": s, "modified": s, "target": s, "answer": None}, require_nonempty=True)


def test_nul_is_refused_and_the_message_says_why():
    with pytest.raises(ProblemTextError, match=r"target contains the character U\+0000.*cannot store"):
        check_problem("abc", "abd", "x\x00y")
    with pytest.raises(ProblemTextError, match=r"answer contains the character U\+0000"):
        check_problem("abc", "abd", "xyz", "\x00")


@pytest.mark.parametrize("lone", ["\ud800", "\udfff", "a\udc00b", "\ud83d"])
def test_a_lone_surrogate_is_refused_and_the_message_says_why(lone):
    with pytest.raises(ProblemTextError, match=r"initial is not valid Unicode text.*lone surrogate.*UTF-8"):
        check_problem(lone, "abd", "xyz")


def test_a_valid_surrogate_pair_is_just_an_emoji():
    check_problem("\U0001f600", "abd", "xyz")
    assert "\U0001f600".encode("utf-16", "surrogatepass")  # one character, not two surrogates


def test_structure_is_only_enforced_when_asked_for():
    check_problem("", "", "", "")  # the check itself adds the structure only when asked
    for args, msg in (
        (("", "b", "c"), "initial must not be empty"),
        (("a", "", "c"), "modified must not be empty"),
        (("a", "b", ""), "target must not be empty"),
        (("a", "b", "c", ""), "answer must not be empty"),
    ):
        with pytest.raises(ProblemTextError, match=msg):
            check_problem(*args, require_nonempty=True)
    check_problem("a", "b", "c", None, require_nonempty=True)


def test_non_strings_are_refused():
    with pytest.raises(ProblemTextError, match="initial must be a string"):
        check_problem(1, "b", "c")
    with pytest.raises(ProblemTextError, match="answer must be a string or null"):
        check_problem("a", "b", "c", 3)


@pytest.mark.parametrize("model,extra", [
    (ProblemInput, {}),
])
def test_the_training_mode_request_model_accepts_the_corpus_and_keeps_it_exactly(model, extra):
    for s in CORPUS:
        m = model(initial=s, modified=s, target=s, answer=s, **extra)
        assert (m.initial, m.modified, m.target, m.answer) == (s, s, s, s)
    assert model(initial=NFC, modified=NFD, target="x", **extra).modified == NFD  # never normalised


@pytest.mark.parametrize("model,extra", [
    (ProblemInput, {}),
])
def test_the_training_mode_request_model_refuses_nul_and_a_lone_surrogate_with_a_message(model, extra):
    for bad, msg in (("a\x00", r"U\+0000"), ("\ud800", "not valid Unicode")):
        for field in ("initial", "modified", "target", "answer"):
            values = {"initial": "a", "modified": "b", "target": "c", **extra, field: bad}
            with pytest.raises(ValidationError, match=msg):
                model(**values)


def test_the_training_mode_request_model_keeps_the_structural_rule():
    with pytest.raises(ValidationError, match="initial must not be empty"):
        ProblemInput(initial="", modified="b", target="c")
    with pytest.raises(ValidationError, match="answer must not be empty"):
        ProblemInput(initial="a", modified="b", target="c", answer="")
    assert ProblemInput(initial="a", modified="b", target="c", answer=None).answer is None
    with pytest.raises(ValidationError, match="target must not be empty"):
        ProblemInput(initial="a", modified="b", target="")


def test_check_deep_accepts_any_nesting_of_text_and_names_the_path_of_a_bad_string():
    ok = [{"op": "insert", "row": {"glyph": "👨‍👩‍👧", "name": "長" * 5000, "n": 1, "none": None}}]
    check_deep("ops", ok)
    for bad, word in (("a\x00b", "U+0000"), ("a\ud800b", "surrogate")):
        with pytest.raises(ProblemTextError, match=r"ops\[0\]\['row'\]\['glyph'\]") as exc:
            check_deep("ops", [{"row": {"glyph": bad}}])
        assert word in str(exc.value) and "\x00" not in str(exc.value)
        with pytest.raises(ProblemTextError, match="a key of"):
            check_deep("ops", [{bad: 1}])
        with pytest.raises(ProblemTextError, match="ops"):
            check_deep("ops", {"x": ["fine", [bad]]})
