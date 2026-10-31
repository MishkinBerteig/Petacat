"""A rule's English, against what Metacat 1.2 prints.

``transcribe-to-english`` (``rules.ss:1723``) describes every rule when it is made.
``tests/seed_unit/rule_english_metacat.tsv`` is a record of that output: every distinct
(rule type, clause structure, text) among the 12,582 rules Metacat built over twenty
problems, plus a few probes of its helpers called directly.  The same rules were built
by Petacat replaying the same Metacat traces (the lockstep harness's ``ReplayRNG``) and
every one transcribed identically, rule for rule and codelet for codelet.

The text depends on the strings as well as on the rule -- a descriptor that names two
objects reads "all `b' groups", a string with a whole group reads "whole group" -- so the
table test searches the few string states that could have produced each row rather than
fixing one.  The hand-written tests pin each of those states exactly.

These need the shipped slipnet (names) and ``engine_params.json`` (the wrap width and the
dimension-name table), which is why they sit in this layer.
"""

import itertools
import os
from types import SimpleNamespace

import pytest

from server.engine.metadata import MetadataProvider
from server.engine.rule_english import (
    _new_object_phrase,
    _punctuate,
    transcribe_rule_to_english_lines,
)
from server.engine.rules import (
    CLAUSE_EXTRINSIC,
    CLAUSE_INTRINSIC,
    CLAUSE_VERBATIM,
    RULE_BOTTOM,
    RULE_TOP,
    Rule,
    RuleChange,
    RuleClause,
    rules_equal,
)
from server.engine.slipnet import Slipnet

HERE = os.path.dirname(__file__)
SEED_DIR = os.path.join(HERE, "..", "..", "seed_data")


@pytest.fixture(scope="module")
def meta():
    return MetadataProvider.from_standard_configuration(SEED_DIR)


@pytest.fixture(scope="module")
def nodes(meta):
    return Slipnet.from_metadata(meta).nodes


# --- a stand-in string: just what the transcription asks of one ---------------


class _Obj:
    """A letter or group that carries a descriptor when ``present(name)`` says so."""

    def __init__(self, present, whole=False):
        self._present = present
        self._whole = whole

    def descriptor_present(self, node):
        return self._present(node.name)

    def get_all_descriptions(self):
        if self._whole:
            return [SimpleNamespace(descriptor=SimpleNamespace(name="plato-whole"))]
        return []


def _string(plural=(), whole_group=False):
    """A string in which each descriptor named in ``plural`` is borne by two objects,
    any other descriptor by one, and a whole group exists when ``whole_group``."""
    plural = set(plural)
    first = _Obj(lambda n: n != "plato-whole")
    second = _Obj(lambda n: n in plural)
    groups = [first, second]
    if whole_group:
        groups.append(_Obj(lambda n: n == "plato-whole", whole=True))
    return SimpleNamespace(letters=[first, second], groups=groups)


def _workspace(initial=None, target=None):
    return SimpleNamespace(
        initial_string=initial or _string(), target_string=target or _string()
    )


# --- building rules from the table's clause notation ---------------------------


def _node(nodes, short):
    return short if short == "string" else nodes["plato-" + short]


def _od(nodes, text):
    return tuple(_node(nodes, part) for part in text.split("/"))


def _parse_clause(nodes, text):
    kind, body = text[0], text[2:-1]
    if kind == "V":
        return RuleClause(
            CLAUSE_VERBATIM, verbatim_letters=[_node(nodes, x) for x in body.split(",")]
        )
    if kind == "X":
        ods, dims = body.split("][")
        return RuleClause(
            CLAUSE_EXTRINSIC,
            extrinsic_objects=[_od(nodes, o) for o in ods.split(";")],
            dimensions=[_node(nodes, d) for d in dims.split(",")],
        )
    od, changes = body.split("][")
    built = []
    for change in changes.split(";"):
        scope, dimension, descriptor = change.split(":")
        target = _node(nodes, descriptor)
        relation = target if descriptor in ("successor", "predecessor", "opposite", "identity") else None
        built.append(
            RuleChange(
                dimension=_node(nodes, dimension),
                relation=relation,
                to_descriptor=None if relation else target,
                referent=scope,
            )
        )
    return RuleClause(CLAUSE_INTRINSIC, object_description=_od(nodes, od), changes=built)


def _rule(nodes, rule_type, key, workspace=None):
    clauses = [_parse_clause(nodes, c) for c in key.split("&&")] if key else []
    return Rule(rule_type, clauses, workspace=workspace)


def _lines(nodes, meta, rule_type, key, plural=(), whole_group=False):
    string = _string(plural, whole_group)
    workspace = _workspace(initial=string, target=string)
    return transcribe_rule_to_english_lines(_rule(nodes, rule_type, key, workspace), meta)


def _table():
    path = os.path.join(HERE, "rule_english_metacat.tsv")
    with open(path) as f:
        rows = [line.rstrip("\n").split("\t") for line in f if not line.startswith("#")]
    return [(r[0], r[1], r[2].split("|||")) for r in rows]


def _descriptors_of(key):
    names = set()
    for clause in key.split("&&"):
        if clause.startswith(("I[", "X[")):
            ods = clause[2:-1].split("][")[0]
            for od in ods.split(";"):
                names.add("plato-" + od.split("/")[2])
    return sorted(names)


# --- the table ----------------------------------------------------------------


def test_every_rule_shape_metacat_printed_reads_the_same_in_petacat(nodes, meta):
    """All 463 distinct rules in the record: identity, verbatim, intrinsic with every
    change type and scope, swaps over one or several objects, multi-clause rules and
    lines wrapped at the limit.  A row passes when some string state gives Metacat's
    exact lines."""
    rows = _table()
    assert len(rows) > 400
    failures = []
    for rule_type, key, expected in rows:
        descriptors = _descriptors_of(key) if key else []
        matched = False
        for count in range(len(descriptors) + 1):
            for plural in itertools.combinations(descriptors, count):
                for whole in (False, True):
                    if _lines(nodes, meta, rule_type, key, plural, whole) == expected:
                        matched = True
                        break
                if matched:
                    break
            if matched:
                break
        if not matched:
            failures.append((rule_type, key, expected))
    assert not failures, f"{len(failures)} rules read differently, e.g. {failures[:2]}"


# --- each state, pinned --------------------------------------------------------


def test_an_empty_rule_and_a_verbatim_rule(nodes, meta):
    assert _lines(nodes, meta, RULE_TOP, "") == ["Don't change anything"]
    assert _lines(nodes, meta, RULE_TOP, "V[a,b,d]") == ['Change string to "abd"']


def test_literal_and_relational_changes_are_quoted_and_capitalised_as_metacat_does(nodes, meta):
    key = "I[letter/string-position-category/rightmost][self:letter-category:d]"
    assert _lines(nodes, meta, RULE_TOP, key) == [
        "Change letter-category of rightmost letter to `d'"
    ]
    key = "I[letter/string-position-category/rightmost][self:letter-category:successor]"
    assert _lines(nodes, meta, RULE_TOP, key) == [
        "Change letter-category of rightmost letter to successor"
    ]
    key = "I[letter/letter-category/c][self:letter-category:d]"
    assert _lines(nodes, meta, RULE_TOP, key) == ["Change letter-category of letter `c' to `d'"]


def test_a_descriptor_borne_by_several_objects_makes_the_phrase_plural(nodes, meta):
    key = "I[group/letter-category/b][self:letter-category:c]"
    assert _lines(nodes, meta, RULE_TOP, key) == ["Change letter-category of `b' group to `c'"]
    assert _lines(nodes, meta, RULE_TOP, key, plural=["plato-b"]) == [
        "Change letter-categories of all `b' groups to `c'"
    ]


def test_the_whole_group_reads_as_the_string_until_a_whole_group_exists(nodes, meta):
    key = "I[string/string-position-category/whole][subobjects:length:successor]"
    assert _lines(nodes, meta, RULE_TOP, key) == [
        "Increase lengths of all objects in string by one"
    ]
    assert _lines(nodes, meta, RULE_TOP, key, whole_group=True) == [
        "Increase lengths of all objects in whole group by one"
    ]


def test_long_phrases_wrap_at_the_next_space_with_an_indented_continuation(nodes, meta):
    """``separate-into-multiple-lines``: break at the first space at or after the width,
    and indent the rest by two spaces on top of the space it begins with."""
    key = "I[group/alphabetic-position-category/alphabetic-first][subobjects:length:successor;subobjects:object-category:group]"
    assert _lines(nodes, meta, RULE_BOTTOM, key) == [
        "Increase lengths of all objects in",
        "   alphabetic-first group by one",
    ]


def test_each_dimension_name_and_the_list_punctuation_match_metacat(nodes, meta):
    table = meta.get_param("rule_english_dimension_phrases")
    assert table == {
        "plato-direction-category": ["direction", "directions"],
        "plato-group-category": ["group-type", "group-types"],
        "plato-alphabetic-position-category": ["alphabetic-position", "alphabetic-positions"],
        "plato-letter-category": ["letter-category", "letter-categories"],
        "plato-length": ["length", "lengths"],
        "plato-object-category": ["object-type", "object-types"],
        "plato-string-position-category": ["position", "positions"],
    }
    assert [_punctuate(x) for x in ([], ["a"], ["a", "b"], ["a", "b", "c", "d"])] == [
        "",
        "a",
        "a and b",
        "a, b, c, and d",
    ]


def test_the_article_before_a_new_group_follows_metacats_letter_list(nodes):
    """Probed in Metacat by calling ``new-object-phrase`` on every letter it lists."""
    group = nodes["plato-group"]
    an = "aefhilmnorsx"
    for letter in "abcdefghilmnorstxz":
        expected = ("an" if letter in an else "a") + f" `{letter}' group"
        assert _new_object_phrase(group, nodes["plato-" + letter], False) == expected
        assert _new_object_phrase(group, nodes["plato-" + letter], True) == f"`{letter}' groups"
    letter = nodes["plato-letter"]
    assert _new_object_phrase(letter, nodes["plato-c"], False) == "the letter `c'"
    assert _new_object_phrase(letter, None, False) == "a letter"
    assert _new_object_phrase(letter, nodes["plato-successor"], True) == "letters"
    assert _new_object_phrase(group, None, True) == "groups"


def test_a_rule_is_described_against_its_own_strings_and_the_text_is_kept(nodes, meta):
    """``make-rule`` transcribes once, a top rule against the initial string and a
    bottom rule against the target string (``rules.ss:98``, ``1723``).  A later change
    to the strings does not rewrite what the rule was called."""
    key = "I[string/string-position-category/whole][subobjects:length:successor]"
    workspace = _workspace(initial=_string(whole_group=True), target=_string())
    top = _rule(nodes, RULE_TOP, key, workspace)
    bottom = _rule(nodes, RULE_BOTTOM, key, workspace)
    assert top.transcribe_to_english(meta) == "Increase lengths of all objects in whole group by one"
    assert bottom.transcribe_to_english(meta) == "Increase lengths of all objects in string by one"
    workspace.initial_string = _string(whole_group=False)
    assert top.transcribe_to_english(meta) == "Increase lengths of all objects in whole group by one"
    assert top.english_lines == ["Increase lengths of all objects in whole group by one"]


def test_the_english_is_display_only_rules_compare_by_structure(nodes, meta):
    key = "I[group/letter-category/b][self:letter-category:c]"
    plain = _rule(nodes, RULE_TOP, key, _workspace())
    plural = _rule(nodes, RULE_TOP, key, _workspace(initial=_string(plural=["plato-b"])))
    assert plain.transcribe_to_english(meta) != plural.transcribe_to_english(meta)
    assert rules_equal(plain, plural)
