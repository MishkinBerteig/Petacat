"""A snag's explanation, against what Metacat 1.2 prints.

``make-snag-event``'s ``get-explanation`` (``trace.ss:1097-1125``) writes a sentence from
the *failure-result* a rule application reports -- ``(SWAP objects dimension)``,
``(CONFLICT object1 dimension1 object2 dimension2)`` or ``(CHANGE object transform)`` --
using ``snag-object-phrase`` (``trace.ss:1258``), ``punctuate`` and the slipnodes'
lowercase names.  The commentary capitalises it (``answers.ss:1166``), Episodic Memory
keeps it (``memory.ss:332``), and an answer explanation quotes it (``answers.ss:302``).

Every expected string below is a sentence Metacat 1.2 printed while running (the snag
event's own ``get-explanation``, logged by wrapping ``make-snag-event`` in the
reference container), except where a test says it is derived from the source: the
two-object SWAP (``punctuate``'s "and" branch) and the group-named reversal.  The same
snags were reproduced by Petacat replaying Metacat's traces;
``tests/lockstep/test_snag_explanations.py`` is that half.  Here the
failure-results are built by hand from real Workspace strings and the shipped slipnet,
so a wrong word or a wrong branch shows up as a one-line diff.

These need the shipped slipnet (the nodes' names) and ``commentary_templates.json`` (the
English), which is why they sit in this layer.
"""

from types import SimpleNamespace

import pytest

from server.engine.commentary import CommentaryLog, emit_snag
from server.engine.images import ImageFailure
from server.engine.memory import EpisodicMemory, SnagDescription
from server.engine.metadata import MetadataProvider, default_commentary_templates
from server.engine.slipnet import Slipnet
from server.engine.snag_explanation import (
    capitalize_string,
    explain_failure,
    fallback_explanation,
    snag_explanation_text,
    snag_object_phrase,
)
from server.engine.workspace import WorkspaceString

import os

SEED_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "seed_data")


@pytest.fixture(scope="module")
def nodes():
    return Slipnet.from_metadata(MetadataProvider.from_seed_data(SEED_DIR)).nodes


@pytest.fixture(scope="module")
def slipnet():
    return Slipnet.from_metadata(MetadataProvider.from_seed_data(SEED_DIR))


def _string(slipnet, text):
    return WorkspaceString(text, slipnet, "target")


class _Group:
    """What ``snag-object-phrase`` asks of a group: its letters and its string."""

    def __init__(self, string, left, right):
        self.string = string
        self._letters = string.letters[left : right + 1]

    def get_letters(self):
        return self._letters


def _letter(string, i):
    return string.letters[i]


def _swap(objects, dimension):
    return ImageFailure("swap", objects=objects, kind=ImageFailure.SWAP, dimension=dimension)


def _change(obj, dimension, descriptor, *extra):
    return ImageFailure(
        "change", objects=[obj], kind=ImageFailure.CHANGE,
        transform=(dimension, descriptor, *extra),
    )


# --- the object phrase ---------------------------------------------------------


def test_object_phrases_follow_trace_ss_1258(slipnet):
    s = _string(slipnet, "xyz")
    assert snag_object_phrase(s) == 'the string "xyz"'
    assert snag_object_phrase(_letter(s, 2)) == "the letter z"
    assert snag_object_phrase(_Group(s, 0, 2)) == "the xyz group"
    assert snag_object_phrase(_Group(s, 1, 2)) == "the yz group"


# --- CHANGE: the transform's descriptor is a relation or a literal ----------------


def test_change_by_a_relation_says_its_name(nodes, slipnet):
    """Metacat: abc -> abd; xyz, seed 1, codelet 273."""
    s = _string(slipnet, "xyz")
    failure = _change(_letter(s, 2), nodes["plato-letter-category"], nodes["plato-successor"])
    assert explain_failure(failure) == (
        "changing the letter-category of the letter z to its successor "
        "is not possible in xyz"
    )


def test_change_to_a_predecessor_of_a_letter(nodes, slipnet):
    """Metacat: wxyz -> vxyz; abcd -> ?"""
    s = _string(slipnet, "abcd")
    failure = _change(_letter(s, 0), nodes["plato-letter-category"], nodes["plato-predecessor"])
    assert explain_failure(failure) == (
        "changing the letter-category of the letter a to its predecessor "
        "is not possible in abcd"
    )


def test_change_to_a_literal_is_quoted_Scheme_style(nodes, slipnet):
    """A non-relation descriptor reads `x' -- backquote, quote (``trace.ss:1124``)."""
    s = _string(slipnet, "xyz")
    failure = _change(_Group(s, 0, 2), nodes["plato-letter-category"], nodes["plato-z"])
    assert explain_failure(failure) == (
        "changing the letter-category of the xyz group to `z' is not possible in xyz"
    )
    failure = _change(_Group(s, 0, 2), nodes["plato-length"], nodes["plato-four"])
    assert explain_failure(failure) == (
        "changing the length of the xyz group to `four' is not possible in xyz"
    )


def test_change_of_a_whole_string_names_the_string(nodes, slipnet):
    """The object of a CHANGE can be a workspace string (``answers.ss:1143``)."""
    s = _string(slipnet, "xyzw")
    failure = _change(s, nodes["plato-length"], nodes["plato-predecessor"])
    assert explain_failure(failure) == (
        'changing the length of the string "xyzw" to its predecessor '
        "is not possible in xyzw"
    )
    z = _string(slipnet, "zy")
    failure = _change(z, nodes["plato-object-category"], nodes["plato-letter"])
    assert explain_failure(failure) == (
        'changing the object-category of the string "zy" to `letter\' '
        "is not possible in zy"
    )


def test_alphabetic_position_opposite(nodes, slipnet):
    s = _string(slipnet, "abc")
    failure = _change(
        _letter(s, 2), nodes["plato-alphabetic-position-category"], nodes["plato-opposite"]
    )
    assert explain_failure(failure) == (
        "changing the alphabetic-position-category of the letter c to its opposite "
        "is not possible in abc"
    )


# --- SWAP ----------------------------------------------------------------------


def test_swap_lists_the_objects_with_punctuate(nodes, slipnet):
    """Metacat: abc -> abd; mrrjjj, the three-object list with an Oxford comma."""
    s = _string(slipnet, "mrrjjj")
    failure = _swap(
        [_Group(s, 0, 0), _Group(s, 1, 2), _Group(s, 3, 5)], nodes["plato-letter-category"]
    )
    assert explain_failure(failure) == (
        "no letter-category swap is possible between the m group, the rr group, "
        "and the jjj group in mrrjjj"
    )


def test_a_swap_of_two_objects_is_joined_with_and(nodes, slipnet):
    """Derived from ``punctuate`` (``rules.ss:1824``); no two-object swap was observed."""
    s = _string(slipnet, "xyz")
    failure = _swap([_letter(s, 0), _letter(s, 1)], nodes["plato-letter-category"])
    assert explain_failure(failure) == (
        "no letter-category swap is possible between the letter x and the letter y in xyz"
    )


def test_a_string_position_swap_uses_the_nodes_full_lowercase_name(nodes, slipnet):
    """Metacat: ``get-lowercase-name`` is the symbol minus ``plato-``, so the dimension
    reads "string-position-category", not "string-position"."""
    s = _string(slipnet, "xyz")
    failure = _swap(
        [_letter(s, 0), _letter(s, 1), _letter(s, 2)],
        nodes["plato-string-position-category"],
    )
    assert explain_failure(failure) == (
        "no string-position-category swap is possible between the letter x, "
        "the letter y, and the letter z in xyz"
    )


# --- CONFLICT -------------------------------------------------------------------


def test_conflict_names_both_changes(nodes, slipnet):
    """Metacat: abc -> cba; xyz -> ?, seed 9, codelet 825 (28 such snags in all)."""
    s = _string(slipnet, "xyz")
    g = _Group(s, 0, 2)
    failure = ImageFailure(
        "conflict", objects=[g, g], kind=ImageFailure.CONFLICT,
        dimension=nodes["plato-group-category"], dimension2=nodes["plato-letter-category"],
    )
    assert explain_failure(failure) == (
        "changing the group-category of the xyz group conflicts with changing the "
        "letter-category of the xyz group in xyz"
    )


# --- group-category reversal ------------------------------------------------------


def test_reversing_a_group_uses_the_bond_facet(nodes, slipnet):
    """``trace.ss:1111``: a (GroupCtgy Opposite facet) transform is a reversal.
    Metacat: abc -> cba; abcabc -> ?, seed 3, codelet 1217 -- the object is the string."""
    s = _string(slipnet, "abcabc")
    failure = _change(
        s, nodes["plato-group-category"], nodes["plato-opposite"],
        nodes["plato-letter-category"],
    )
    assert explain_failure(failure) == (
        'reversing the starting and ending letter-category of the string "abcabc" '
        "is not possible in abcabc"
    )
    # The same branch names a group by its letters (the phrase is shared).
    group = _Group(s, 0, 2)
    failure = _change(
        group, nodes["plato-group-category"], nodes["plato-opposite"], nodes["plato-length"]
    )
    assert explain_failure(failure) == (
        "reversing the starting and ending length of the abc group "
        "is not possible in abcabc"
    )


# --- failures that carry too little ------------------------------------------------


def test_a_failure_without_its_result_has_no_explanation(nodes, slipnet):
    """Petacat can fail where Metacat's rule application cannot (an object with no
    image); there is no Metacat sentence for that, so the caller falls back."""
    s = _string(slipnet, "xyz")
    assert explain_failure(None) is None
    assert explain_failure(ImageFailure("no image", objects=[s])) is None
    assert explain_failure(ImageFailure("x", objects=[])) is None


# --- capitalisation and the commentary ------------------------------------------------


def test_capitalize_string_changes_only_the_first_character():
    """``utilities.ss:330-336``."""
    assert capitalize_string("changing the length of Z") == "Changing the length of Z"
    assert capitalize_string("") == ""
    assert capitalize_string("`a'") == "`a'"


EXPLANATION = (
    "changing the letter-category of the letter z to its successor "
    "is not possible in xyz"
)


def test_snag_commentary_is_metacats_two_lines():
    """``answers.ss:1164-1172``, both voices, first snag and a later one.  The strings
    are the CMT lines logged from Metacat 1.2 (abc -> abd; xyz, seed 1)."""
    log = CommentaryLog()
    emit_snag(log, capitalize_string(EXPLANATION), 1, 273)
    emit_snag(log, capitalize_string(EXPLANATION), 2, 421)
    p1, p2 = log.get_paragraphs()
    assert p1.eliza_text == (
        "Uh-oh, I seem to have run into a little problem.  Changing the "
        "letter-category of the letter z to its successor is not possible in xyz."
    )
    assert p1.technical_text == (
        "Hit a snag:  Changing the letter-category of the letter z to its successor "
        "is not possible in xyz."
    )
    assert p2.eliza_text == (
        "Uh-oh, I seem to have run into a little problem again.  Changing the "
        "letter-category of the letter z to its successor is not possible in xyz."
    )
    assert p2.technical_text.startswith("Hit another snag:  Changing the")


def test_the_commentary_words_come_from_the_templates():
    """Step 0: an edited template changes the commentary, nothing is in Python."""
    templates = {
        "answer_reporting": {
            "snag": {
                "eliza": "Hmm{again}: {explanation}!",
                "technical": "SNAG({another}) {explanation}",
                "again": " (again)",
                "first_article": "1st",
                "another_article": "nth",
            }
        }
    }
    log = CommentaryLog()
    emit_snag(log, "Boom", 2, 5, templates)
    (p,) = log.get_paragraphs()
    assert p.eliza_text == "Hmm (again): Boom!"
    assert p.technical_text == "SNAG(nth) Boom"


def test_the_explanation_words_come_from_the_templates(nodes, slipnet):
    templates = dict(default_commentary_templates())
    templates["snag_explanation"] = dict(
        templates["snag_explanation"], change="CHANGE {dimension}|{object}|{descriptor}|{string}"
    )
    s = _string(slipnet, "xyz")
    failure = _change(_letter(s, 2), nodes["plato-letter-category"], nodes["plato-z"])
    assert explain_failure(failure, templates) == (
        "CHANGE letter-category|the letter z|`z'|xyz"
    )


# --- what memory keeps, and the fallback for a snag that has none -----------------------


def _snag(**kwargs):
    return SnagDescription(
        problem=("abc", "abd", "xyz"), codelet_count=1, temperature=50.0,
        theme_pattern={}, description="Replace letter category of rightmost letter by successor",
        **kwargs,
    )


def test_a_snag_description_keeps_the_explanation_and_the_translated_rule():
    snag = _snag(
        explanation=EXPLANATION,
        translated_rule_description="Change letter-category of letter `z' to its successor",
    )
    assert snag_explanation_text(snag) == EXPLANATION
    assert snag.translated_rule_description.startswith("Change letter-category")


def test_a_snag_with_no_stored_explanation_falls_back_to_the_old_sentence():
    """Rows written before the explanation was stored rehydrate with ``explanation=""``;
    the fallback template (``caveat_templates.snag_explanation``) serves them."""
    snag = _snag()
    assert snag.explanation == ""
    assert snag_explanation_text(snag) == (
        'the rule "Replace letter category of rightmost letter by successor" '
        "cannot be applied to xyz"
    )
    assert fallback_explanation("a\n  b", "xyz") == 'the rule "a; b" cannot be applied to xyz'


def test_the_answer_caveat_quotes_the_stored_explanation():
    """``get-snag-explanation`` (``answers.ss:302-307``) returns the snag's own
    sentence, not one rebuilt from the rule."""
    from server.engine.answer_comparison import snag_explanation_for

    memory = EpisodicMemory()
    snag = _snag(explanation=EXPLANATION, rule_signature=["sig"])
    memory.store_snag(snag)
    answer = SimpleNamespace(
        problem=("abc", "abd", "xyz", "xyd"), top_rule_signature=["sig"]
    )
    memory.get_equivalent_snag = lambda a: snag  # the lookup is tested elsewhere
    assert snag_explanation_for(answer, memory, default_commentary_templates()) == EXPLANATION
