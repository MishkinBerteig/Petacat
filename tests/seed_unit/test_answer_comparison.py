"""Unit tests for the answer-comparison and answer-explanation English.

The authority is ``Metacat/answers.ss``: ``theme-phrases`` (336-425),
``get-answer-comparison-text`` (434-882) and ``explain`` (310-333), together with the
dissertation's own walk-through of the ``dyz`` / ``xyd`` comparison at §4.7.4.

Every assertion here is about *which* template gets chosen and how it is filled, never
about the wording itself — the wording lives in ``seed_data/commentary_templates.json``
and is meant to be editable.  ``test_the_prose_is_seed_data_not_python`` is the test
that pins that property down.
"""

import pytest

from server.engine.answer_comparison import (
    all_themes_of,
    coherence_phrase,
    coherence_score,
    compare_answers_text,
    compare_rule_signatures,
    count_rule_differences,
    explain_answer,
    punctuate_with_commas,
    snag_justified_themes,
    theme_phrases,
)
from server.engine.memory import AnswerDescription, EpisodicMemory, SnagDescription
from server.engine.metadata import default_commentary_templates

STRING_POSITION = "plato-string-position-category"
DIRECTION = "plato-direction-category"
GROUP_CATEGORY = "plato-group-category"
BOND_FACET = "plato-bond-facet"
ALPHABETIC = "plato-alphabetic-position-category"


@pytest.fixture
def templates():
    return default_commentary_templates()


def _answer(
    problem,
    themes,
    *,
    unjustified=None,
    rule="the rule",
    rule_abstractness=20.0,
    theme_abstractness=0.0,
    quality=70.0,
    signature=None,
):
    return AnswerDescription(
        problem=problem,
        top_rule_description=rule,
        bottom_rule_description="",
        top_rule_quality=70.0,
        bottom_rule_quality=0.0,
        quality=quality,
        temperature=30.0,
        themes=dict(themes),
        unjustified_slippages=[],
        unjustified_themes=dict(unjustified or {}),
        top_rule_abstractness=rule_abstractness,
        theme_abstractness=theme_abstractness,
        top_rule_signature=signature,
    )


#: The two answers of Table 4.2 — the pair §4.7.4 works through in full.
def _dyz():
    return _answer(
        ("abc", "abd", "xyz", "dyz"),
        {
            STRING_POSITION: "opposite",
            DIRECTION: "opposite",
            GROUP_CATEGORY: "opposite",
            ALPHABETIC: "opposite",
        },
        rule_abstractness=20.0,
        theme_abstractness=70.0,
        quality=71.0,
    )


def _xyd():
    return _answer(
        ("abc", "abd", "xyz", "xyd"),
        {
            STRING_POSITION: "identity",
            DIRECTION: "identity",
            GROUP_CATEGORY: "identity",
        },
        rule_abstractness=60.0,
        theme_abstractness=30.0,
        quality=85.0,
    )


# ---------------------------------------------------------------------------
# punctuate-with-commas  (answers.ss:267-276)
# ---------------------------------------------------------------------------


def test_two_phrases_keep_the_comma_before_the_conjunction():
    """``answers.ss:272`` renders two items as "a, and b", not "a and b".

    The comma is the Scheme's, and dropping it would quietly re-punctuate every
    two-theme sentence the program produces.
    """
    assert punctuate_with_commas("and", ["a", "b"]) == "a, and b"


def test_three_phrases_are_serial_commas_with_the_conjunction_last():
    """``answers.ss:273-276``."""
    assert punctuate_with_commas("or", ["a", "b", "c"]) == "a, b, or c"


# ---------------------------------------------------------------------------
# theme-phrases  (answers.ss:336-425)
# ---------------------------------------------------------------------------


def _phrase(templates, themes, **kwargs):
    kwargs.setdefault("snag_justified_themes", [])
    kwargs.setdefault("unjustified_themes", [])
    kwargs.setdefault("initial", "abc")
    kwargs.setdefault("target", "xyz")
    return theme_phrases(
        templates, prep="on ", conj="and", ending="ing", themes=themes, **kwargs
    )


def test_group_category_and_direction_are_chosen_independently(templates):
    """``answers.ss:362-382`` fills the group qualifier from Group-Category and the
    direction from String-Position, in two separate ``cond``s.

    They are two independent lookups, so the four Group-Category and String-Position
    relations combine freely: an answer can see the strings as symmetric predecessor and
    successor groups that nonetheless run the same way.
    """
    phrase = _phrase(
        templates, [(GROUP_CATEGORY, "opposite"), (STRING_POSITION, "identity")]
    )
    assert (
        phrase
        == "on seeing abc and xyz as symmetric predecessor and successor groups "
        "going in the same direction"
    )


def test_an_unjustified_group_category_is_not_asserted_as_a_qualifier(templates):
    """``answers.ss:366-368``: the program does not describe the strings as groups of
    some type when it never justified seeing them that way."""
    theme = (GROUP_CATEGORY, "identity")
    phrase = _phrase(
        templates,
        [(STRING_POSITION, "identity")],
        unjustified_themes=[theme],
    )
    assert "groups of the same type" not in phrase
    assert "going in the same direction" in phrase


def test_bond_facet_folds_into_the_group_clause_when_there_is_no_string_position(
    templates,
):
    """``answers.ss:396-400``: with only a Group-Category theme, the letters/numbers
    contrast is a subordinate clause of it rather than a phrase of its own."""
    phrase = _phrase(templates, [(GROUP_CATEGORY, "identity"), (BOND_FACET, "diff")])
    assert phrase == (
        "on seeing abc and xyz as groups of the same type by viewing one string in "
        "terms of letters and the other in terms of numbers"
    )


def test_bond_facet_gets_its_own_phrase_alongside_string_position(templates):
    """``answers.ss:403-406``: once String-Position has claimed the "seeing ... as ..."
    sentence, Bond-Facet needs a clause of its own."""
    phrase = _phrase(templates, [(STRING_POSITION, "identity"), (BOND_FACET, "diff")])
    assert phrase == (
        "on seeing abc and xyz as going in the same direction, and on viewing one of "
        "the strings in terms of letters and the other in terms of numbers"
    )


def test_the_strings_are_named_once_and_then_referred_to(templates):
    """§4.7.4 p. 195: slot 4 of the alphabetic-position template "is simply 'the
    strings', since abc and xyz have already been explicitly mentioned"."""
    phrase = _phrase(
        templates, [(STRING_POSITION, "opposite"), (ALPHABETIC, "opposite")]
    )
    assert phrase.count("abc and xyz") == 1
    assert "alphabetic-position symmetry between the strings" in phrase


def test_direction_themes_are_never_described_on_their_own(templates):
    """``answers.ss:341``: "Direction-theme should always be the same as
    StringPos-theme", so ``theme-phrases`` looks Direction up nowhere and the
    String-Position phrase speaks for both."""
    assert _phrase(templates, [(DIRECTION, "opposite")]) == ""


def test_an_unjustified_theme_carries_the_no_good_reason_caveat(templates):
    """``answers.ss:352-353``, and §4.7.4 p. 195: "in the case of unjustified themes,
    the phrase '(although there is no good reason for doing so)' would be added"."""
    theme = (ALPHABETIC, "opposite")
    phrase = _phrase(
        templates, [], unjustified_themes=[theme], add_caveats=True
    )
    assert phrase.endswith("(although there is no good reason for doing so)")


def test_a_snag_justified_theme_carries_the_snag_it_avoids(templates):
    """``answers.ss:354-357`` and §4.7.4 p. 195: the caveat quotes *why* the snag would
    have arisen, which is the whole content of §4.7.3's aaabccc / aaabaaa distinction.

    A snag-justified theme is one the answer *holds* (so it is among ``themes``) and
    separately failed to justify — ``explain`` at ``answers.ss:317-320`` subtracts it
    from the unjustified list precisely so it gets this caveat instead of the other one.
    """
    theme = (BOND_FACET, "diff")
    phrase = _phrase(
        templates,
        [theme],
        snag_justified_themes=[theme],
        unjustified_themes=[],
        add_caveats=True,
        snag_explanation="z has no successor",
    )
    assert phrase.endswith(
        "(which avoids a snag that would otherwise arise from the fact that "
        "z has no successor)"
    )


def test_caveats_are_omitted_where_the_scheme_omits_them(templates):
    """``answers.ss:350-351``: ``add-caveats?`` is false for the "similarities" and
    unique-theme clauses, which are describing ideas, not vouching for them."""
    theme = (ALPHABETIC, "opposite")
    phrase = _phrase(templates, [], unjustified_themes=[theme], add_caveats=False)
    assert "although" not in phrase


# ---------------------------------------------------------------------------
# explain  (answers.ss:310-333)
# ---------------------------------------------------------------------------


def test_explain_names_what_the_answer_rests_on(templates):
    """``answers.ss:321-325``: "This answer is based ⟨theme phrases⟩."."""
    result = explain_answer(_xyd(), None, templates)
    assert result["explanation"] == (
        "This answer is based on seeing abc and xyz as groups of the same type "
        "going in the same direction."
    )


def test_explain_keeps_the_two_voices_isomorphic(templates):
    """``answers.ss:326-333`` builds both voices from the *same* explanation and differs
    only in the closing sentence — §4.6 pp. 183-184: "the commentary produced by the
    program when running in one mode is isomorphic to the commentary produced in the
    other mode"."""
    result = explain_answer(_xyd(), None, templates)
    assert result["eliza_text"].startswith(result["explanation"])
    assert result["technical_text"].startswith(result["explanation"])
    assert result["eliza_text"].endswith("I think this answer is very good.")
    assert result["technical_text"].endswith("Answer quality = 85.")


# ---------------------------------------------------------------------------
# Snag-justified themes  (answers.ss:285-299, §4.7.3)
# ---------------------------------------------------------------------------


def test_only_themes_the_snag_lacked_count_as_snag_justified():
    """``answers.ss:293-298`` subtracts the snag's own theme-pattern before intersecting
    with the unjustified themes.

    §4.7.3: it is "the differences between the themes involved in the snag and the
    themes involved in the answer" that show how the snag was avoided.  A theme the
    snag episode *also* had cannot be what avoided it.
    """
    memory = EpisodicMemory()
    rule = "Swap letter-categories of all objects in string"
    # ``get-equivalent-snag`` (``memory.ss:84-89``) matches the answer's top-rule
    # *clause list* against the snag's, so both carry the same signature.
    signature = [["intrinsic", [], []]]
    answer = _answer(
        ("eqe", "qeq", "abbbc", "aaabccc"),
        {STRING_POSITION: "identity"},
        unjustified={BOND_FACET: "diff"},
        rule=rule,
        signature=signature,
    )
    memory.store_snag(
        SnagDescription(
            problem=("eqe", "qeq", "abbbc"),
            codelet_count=500,
            temperature=40.0,
            theme_pattern={STRING_POSITION: "identity"},
            description=rule,
            rule_signature=signature,
        )
    )
    assert snag_justified_themes(answer, memory) == [(BOND_FACET, "diff")]


def test_a_theme_the_snag_also_held_stays_unjustified():
    """The converse of the above (``answers.ss:293``): a theme the snag episode held
    too stays unjustified, since it is not what the answer did differently."""
    memory = EpisodicMemory()
    rule = "Swap letter-categories of all objects in string"
    signature = [["intrinsic", [], []]]
    answer = _answer(
        ("eqe", "qeq", "abbbc", "aaabccc"),
        {},
        unjustified={BOND_FACET: "diff"},
        rule=rule,
        signature=signature,
    )
    memory.store_snag(
        SnagDescription(
            problem=("eqe", "qeq", "abbbc"),
            codelet_count=500,
            temperature=40.0,
            theme_pattern={BOND_FACET: "diff"},
            description=rule,
            rule_signature=signature,
        )
    )
    assert snag_justified_themes(answer, memory) == []


def test_unjustified_themes_are_part_of_what_an_answer_rests_on():
    """``answers.ss:456-464``: ``all-themes`` is themes *and* unjustified themes.

    The comparison classifies over that union, which is what lets §4.7.3's aaabccc and
    aaabaaa — whose only theme in common is an unjustified one — be compared at all.
    """
    answer = _answer(
        ("abc", "abd", "xyz", "xyd"),
        {STRING_POSITION: "identity"},
        unjustified={BOND_FACET: "diff"},
    )
    assert all_themes_of(answer) == [
        (STRING_POSITION, "identity"),
        (BOND_FACET, "diff"),
    ]


# ---------------------------------------------------------------------------
# Rule comparison  (answers.ss:598-620)
# ---------------------------------------------------------------------------


def test_rules_of_different_shape_are_not_comparable():
    """``answers.ss:614-615``: when ``compare-rule-clause-lists`` returns ``#f`` the
    change is described as viewed "in a completely different way" — abstractness is not
    consulted, because there is nothing to line up."""
    assert compare_rule_signatures([["a"]], [["a"], ["b"]]) is None
    assert count_rule_differences(None) == -1


def test_concepts_of_equal_depth_are_not_a_rule_difference():
    """``answers.ss:605-610`` drops pairs whose conceptual depths agree.

    "The only essential difference ..." is a claim about *level*: swapping successor for
    predecessor changes the rule without changing how abstract it is.
    """

    class _Spec:
        def __init__(self, depth):
            self.conceptual_depth = depth

    class _Meta:
        slipnet_node_specs = {
            "plato-successor": _Spec(50),
            "plato-predecessor": _Spec(50),
            "plato-letter-category": _Spec(30),
        }

    differences = compare_rule_signatures(
        [["plato-successor"]], [["plato-predecessor"]]
    )
    assert differences == [("plato-successor", "plato-predecessor")]
    assert count_rule_differences(differences, _Meta()) == 0


def test_a_clause_type_mismatch_makes_the_rules_incomparable():
    """``traverse-rule-clauses`` fails on two *symbols* that are not the same symbol
    (``justify.ss:242``), and a clause's type is the first symbol the walk reaches.

    The distinction matters because it is not recoverable afterwards.  Flattened into
    strings, ``intrinsic`` against ``verbatim`` reads as one more pair to compare;
    neither token names a Slipnet node, so both score depth 0, the depth filter at
    ``answers.ss:607-609`` discards the pair, and two rules with nothing whatever in
    common come out *zero* apart.
    """
    intrinsic = [
        [
            "intrinsic",
            ["plato-letter", "plato-string-position-category", "plato-rightmost"],
            [["plato-letter-category", "plato-c", "plato-d", "plato-successor"]],
        ]
    ]
    verbatim = [["verbatim", ["plato-x", "plato-y", "plato-d"]]]
    assert compare_rule_signatures(intrinsic, verbatim) is None
    assert compare_rule_signatures(verbatim, intrinsic) is None


def test_two_verbatim_rules_are_compared_whole_not_letter_by_letter():
    """``compare-rule-clause-lists`` short-circuits verbatim clause lists
    (``justify.ss:256-260``) to "equal, or not comparable at all".

    Walking into them instead would produce a pair per letter, and every letter node
    sits at depth 10, so the depth filter would discard the lot: two verbatim rules
    spelling different strings would measure identical rather than taking the
    abstractness fallback the Scheme gives them.
    """
    spelled_xyd = [["verbatim", ["plato-x", "plato-y", "plato-d"]]]
    spelled_wyz = [["verbatim", ["plato-w", "plato-y", "plato-z"]]]
    assert compare_rule_signatures(spelled_xyd, list(spelled_xyd)) == []
    assert compare_rule_signatures(spelled_xyd, spelled_wyz) is None


def test_clauses_of_different_internal_shape_are_not_comparable():
    """``justify.ss:237-241``: the walk recurs pairwise and fails the moment one side
    runs out, so a clause carrying two changes cannot be lined up against one carrying
    a single change."""
    one_change = [
        [
            "intrinsic",
            ["plato-letter", "plato-string-position-category", "plato-rightmost"],
            [["plato-letter-category", "plato-c", "plato-d", "plato-successor"]],
        ]
    ]
    two_changes = [
        [
            "intrinsic",
            ["plato-letter", "plato-string-position-category", "plato-rightmost"],
            [
                ["plato-letter-category", "plato-c", "plato-d", "plato-successor"],
                ["plato-length", "plato-one", "plato-two", "plato-successor"],
            ],
        ]
    ]
    assert compare_rule_signatures(one_change, two_changes) is None


def test_an_abstract_rule_and_a_literal_one_line_up_slot_for_slot():
    """§4.7.4's rule contrast: "abc => abd is viewed in a more abstract way for the
    answer xyd than in the case of dyz".

    The Scheme's change is ``(scope dimension descriptor)`` (``rules.ss:900-909``) and
    that single descriptor slot holds ``plato-successor`` for the abstract reading and
    ``plato-d`` for the literal one, so the two rules *are* alignable and differ by one
    concept pair — 50 against 10, a real difference in level.

    ``RuleChange`` fills one of ``to_descriptor`` and ``relation`` and leaves the other
    ``None``, in different positions for the two readings.  Compared position by
    position that reads as a structural mismatch, and §4.7.4's canonical pair comes out
    "viewed in a completely different way" with the pair count replaced by an
    abstractness guess.
    """
    abstract = [
        [
            "intrinsic",
            ["plato-letter", "plato-string-position-category", "plato-rightmost"],
            [["plato-letter-category", None, None, "plato-successor"]],
        ]
    ]
    literal = [
        [
            "intrinsic",
            ["plato-letter", "plato-string-position-category", "plato-rightmost"],
            [["plato-letter-category", None, "plato-d", None]],
        ]
    ]
    differences = compare_rule_signatures(abstract, literal)
    assert differences == [("plato-successor", "plato-d")]
    assert count_rule_differences(differences) == 1


def test_the_depth_filter_falls_back_to_the_shipped_conceptual_depths():
    """``count_rule_differences`` is reached from ``EpisodicMemory.distance`` with no
    ``MetadataProvider`` in hand (``find_remindings`` has none), so the filter has to
    have depths of its own or it silently stops filtering.

    ``seed_data/slipnet_nodes.json``: leftmost and rightmost are both 40, successor is
    50 and sameness is 80.
    """
    assert count_rule_differences([("plato-leftmost", "plato-rightmost")]) == 0
    assert count_rule_differences([("plato-successor", "plato-sameness")]) == 1


# ---------------------------------------------------------------------------
# The comparison paragraph  (answers.ss:670-805)
# ---------------------------------------------------------------------------


def test_the_worked_example_reads_as_section_4_7_4_describes_it(templates):
    """§4.7.4 pp. 193-197 walks through dyz vs xyd template by template.

    Asserted here: the "The answer ... is based ..., while the answer ... is based ..."
    frame chosen because both answers have themes the other lacks; the full description
    on first mention and the bare name afterwards; the unique-theme sentence for dyz's
    Alphabetic-Position: opposite; the incoherence remark for dyz; and the verdict
    "since it is more coherent".
    """
    text = compare_answers_text(_dyz(), _xyd(), None, templates)["text"]
    assert text.startswith(
        'The answer dyz to the problem "abc -> abd, xyz -> ?" is based on seeing '
        "abc and xyz as symmetric predecessor and successor groups going in "
        "opposite directions"
    )
    assert ", while the answer xyd is based on seeing" in text
    assert "In xyd's case, the idea of seeing alphabetic-position symmetry" in text
    assert "The answer dyz, however, seems incoherent to me" in text
    assert text.endswith("I'd say xyd is the better answer, since it is more coherent.")


def test_the_second_answer_is_named_without_repeating_the_problem(templates):
    """``answers.ss:448-451``: the problem is named on first mention only, and dropped
    entirely for the second answer when both answers answer the same problem."""
    text = compare_answers_text(_dyz(), _xyd(), None, templates)["text"]
    assert text.count('to the problem "abc -> abd, xyz -> ?"') == 1


def test_answers_to_different_problems_each_name_their_problem(templates):
    """``answers.ss:450``: ``answer1-phrase`` keeps the full description whenever the
    two problems differ, because "xyu" alone would not say which problem it answers."""
    a = _answer(("abc", "abd", "xyz", "xyd"), {STRING_POSITION: "identity"})
    b = _answer(("rst", "rsu", "xyz", "xyu"), {STRING_POSITION: "opposite"})
    text = compare_answers_text(a, b, None, templates)["text"]
    assert 'xyd to the problem "abc -> abd, xyz -> ?"' in text
    assert 'xyu to the problem "rst -> rsu, xyz -> ?"' in text


def test_two_answers_spelled_the_same_are_told_apart_by_ordinal(templates):
    """``answers.ss:629-637``: "the first dyz" / "the second dyz".

    Two answers that spell the same are referred to by ordinal throughout, so the
    verdict names one of them unambiguously.
    """
    a = _answer(
        ("abc", "abd", "xyz", "dyz"),
        {STRING_POSITION: "opposite"},
        unjustified={BOND_FACET: "diff"},
    )
    b = _answer(("abc", "abd", "xyz", "dyz"), {STRING_POSITION: "opposite"})
    text = compare_answers_text(a, b, None, templates)["text"]
    assert "the second dyz is the better answer" in text


def test_in_part_appears_only_when_the_answers_share_ideas(templates):
    """``answers.ss:713``: "in part" qualifies the description when common themes exist
    beyond the ones being contrasted."""
    shared = _answer(
        ("abc", "abd", "xyz", "xyd"),
        {STRING_POSITION: "identity", GROUP_CATEGORY: "identity"},
    )
    other = _answer(
        ("abc", "abd", "xyz", "dyz"),
        {STRING_POSITION: "opposite", GROUP_CATEGORY: "identity"},
    )
    with_common = compare_answers_text(shared, other, None, templates)["text"]
    assert "is based in part on seeing" in with_common

    unshared_a = _answer(("abc", "abd", "xyz", "xyd"), {STRING_POSITION: "identity"})
    unshared_b = _answer(("abc", "abd", "xyz", "dyz"), {STRING_POSITION: "opposite"})
    without_common = compare_answers_text(unshared_a, unshared_b, None, templates)[
        "text"
    ]
    assert "is based in part" not in without_common


def test_identical_answers_are_called_essentially_the_same(templates):
    """``answers.ss:675-685``: no theme differences, no rule differences and no
    justification differences is the one case where MetaCat says the answers are the
    same idea, and it then says so about the rules too ("Furthermore, ...")."""
    a = _answer(
        ("abc", "abd", "xyz", "xyd"),
        {STRING_POSITION: "identity"},
        signature=[["change", "plato-letter-category"]],
    )
    b = _answer(
        ("rst", "rsu", "xyz", "xyu"),
        {STRING_POSITION: "identity"},
        signature=[["change", "plato-letter-category"]],
    )
    text = compare_answers_text(a, b, None, templates)["text"]
    assert text.startswith("The answer xyd to the problem")
    assert "is essentially the same as the answer" in text
    assert "Both answers rely on seeing two strings (abc and xyz in one case and " in text
    assert (
        "Furthermore, the change from abc to abd is viewed in essentially the same "
        "way as the change from rst to rsu." in text
    )


def test_a_rule_difference_alone_is_the_only_essential_difference(templates):
    """``answers.ss:686-692``: same themes, different rules — MetaCat leads with the
    rule sentence rather than with a theme contrast."""
    a = _answer(
        ("abc", "abd", "xyz", "xyd"),
        {STRING_POSITION: "identity"},
        rule_abstractness=70.0,
        signature=[["change", "plato-letter-category"]],
    )
    b = _answer(
        ("abc", "abd", "xyz", "xyd"),
        {STRING_POSITION: "identity"},
        rule_abstractness=20.0,
        signature=[["change", "plato-length"]],
    )
    text = compare_answers_text(a, b, None, templates)["text"]
    assert text.startswith(
        "The only essential difference between the answer xyd and the answer xyd"
    )
    assert "is viewed in a more abstract way for the first answer" in text


def test_the_rule_sentence_is_a_second_sentence_when_the_themes_differ_too(templates):
    """``answers.ss:763-771``: with theme differences already stated, the rule
    difference becomes "Another key difference ..." rather than the opening claim."""
    a = _answer(
        ("abc", "abd", "xyz", "xyd"),
        {STRING_POSITION: "identity"},
        rule_abstractness=20.0,
        signature=[["change", "plato-letter-category"]],
    )
    b = _answer(
        ("abc", "abd", "xyz", "dyz"),
        {STRING_POSITION: "opposite"},
        rule_abstractness=70.0,
        signature=[["change", "plato-length"]],
    )
    text = compare_answers_text(a, b, None, templates)["text"]
    assert "Another key difference between the answers" in text
    assert "is viewed in a more literal way for the answer xyd" in text


def test_an_answer_with_one_theme_gets_the_singular_incoherence_wording(templates):
    """``answers.ss:780-782``: "an abstract similarity" against "abstract similarities",
    on the number of themes the incoherent answer has."""
    incoherent = _answer(
        ("abc", "abd", "xyz", "dyz"),
        {STRING_POSITION: "opposite"},
        rule_abstractness=10.0,
        theme_abstractness=80.0,
    )
    coherent = _answer(("abc", "abd", "xyz", "xyd"), {STRING_POSITION: "identity"})
    text = compare_answers_text(incoherent, coherent, None, templates)["text"]
    assert "since it involves seeing an abstract similarity between abc and xyz" in text


# ---------------------------------------------------------------------------
# The verdict  (answers.ss:806-882) and its priority order
# ---------------------------------------------------------------------------


def test_coherence_outranks_the_count_of_unjustified_ideas(templates):
    """``answers.ss:842-847`` sits above ``answers.ss:848-857``.

    Coherence settles the §4.7.4 worked example — xyd wins "since it is more coherent" —
    and it settles it even when the answers also differ in how much they justify.
    """
    incoherent = _answer(
        ("abc", "abd", "xyz", "dyz"),
        {STRING_POSITION: "opposite"},
        rule_abstractness=10.0,
        theme_abstractness=80.0,
    )
    coherent = _answer(
        ("abc", "abd", "xyz", "xyd"),
        {STRING_POSITION: "identity"},
        unjustified={BOND_FACET: "diff"},
    )
    verdict = compare_answers_text(incoherent, coherent, None, templates)["verdict"]
    assert verdict == "All in all, I'd say xyd is the better answer, since it is more coherent."


def test_no_unjustified_ideas_is_said_differently_from_merely_fewer(templates):
    """``answers.ss:850-852``: "no unjustified ideas" when the winner has none at all."""
    clean = _answer(("abc", "abd", "xyz", "xyd"), {STRING_POSITION: "identity"})
    dirty = _answer(
        ("abc", "abd", "xyz", "dyz"),
        {STRING_POSITION: "opposite"},
        unjustified={BOND_FACET: "diff"},
    )
    verdict = compare_answers_text(clean, dirty, None, templates)["verdict"]
    assert verdict.endswith("since it involves no unjustified ideas.")


def test_the_more_abstract_rule_decides_when_the_ideas_agree(templates):
    """``answers.ss:858-866``.

    It applies *only* when there are no theme differences: with the ideas identical the
    rule is the one thing left to prefer an answer for.
    """
    abstract = _answer(
        ("abc", "abd", "xyz", "xyd"),
        {STRING_POSITION: "identity"},
        rule_abstractness=80.0,
        signature=[["change", "plato-letter-category"]],
    )
    literal = _answer(
        ("abc", "abd", "xyz", "xyd"),
        {STRING_POSITION: "identity"},
        rule_abstractness=20.0,
        signature=[["change", "plato-length"]],
    )
    verdict = compare_answers_text(abstract, literal, None, templates)["verdict"]
    assert verdict.endswith(
        "since it involves seeing the change from abc to abd in a more abstract way."
    )


def test_the_more_abstract_rule_does_not_decide_when_the_ideas_differ(templates):
    """``answers.ss:858``: the criterion is guarded by ``(not theme-differences?)``.

    With different themes, an abstract rule is not evidence of a better answer — it may
    be an abstract rule stranded on an interpretation the program could not support.
    """
    abstract = _answer(
        ("abc", "abd", "xyz", "xyd"),
        {STRING_POSITION: "identity", GROUP_CATEGORY: "identity"},
        rule_abstractness=80.0,
        signature=[["change", "plato-letter-category"]],
    )
    literal = _answer(
        ("abc", "abd", "xyz", "dyz"),
        {STRING_POSITION: "opposite"},
        rule_abstractness=20.0,
        signature=[["change", "plato-length"]],
    )
    verdict = compare_answers_text(abstract, literal, None, templates)["verdict"]
    assert verdict.endswith("since it is based on a richer set of ideas.")


def test_two_incoherent_answers_are_ranked_by_how_incoherent(templates):
    """``answers.ss:825-841``: the opening is "Overall, though," rather than "All in
    all," and the reason is comparative — "doesn't seem quite as incoherent as"."""
    worse = _answer(
        ("abc", "abd", "xyz", "dyz"),
        {STRING_POSITION: "opposite", ALPHABETIC: "opposite"},
        rule_abstractness=10.0,
        theme_abstractness=90.0,
    )
    better = _answer(
        ("abc", "abd", "xyz", "wyz"),
        {STRING_POSITION: "opposite"},
        rule_abstractness=10.0,
        theme_abstractness=60.0,
    )
    verdict = compare_answers_text(worse, better, None, templates)["verdict"]
    assert verdict.startswith("Overall, though, I'd say wyz is the better answer")
    assert verdict.endswith("because it doesn't seem quite as incoherent as dyz.")


def test_evenly_matched_answers_are_described_by_quality_instead(templates):
    """``answers.ss:814-823``: with nothing to separate them the program falls back on
    what it thinks of each, and says so in one sentence or two depending on whether the
    quality phrases coincide."""
    a = _answer(("abc", "abd", "xyz", "xyd"), {STRING_POSITION: "identity"}, quality=88.0)
    b = _answer(("abc", "abd", "xyz", "xyu"), {STRING_POSITION: "identity"}, quality=52.0)
    verdict = compare_answers_text(a, b, None, templates)["verdict"]
    assert verdict == "All in all, I'd say xyd is very good and xyu is pretty bad."

    c = _answer(("abc", "abd", "xyz", "xyu"), {STRING_POSITION: "identity"}, quality=87.0)
    same = compare_answers_text(a, c, None, templates)["verdict"]
    assert same == "All in all, I'd say they're both very good answers."


def test_the_judgment_order_comes_from_the_seed_data(templates):
    """``comparison_judgment_priority`` is ``answers.ss:824-882``'s ``cond`` written
    down as data, and it is genuinely consulted.

    Moving "richer_set_of_ideas" above the coherence criteria changes the verdict on the
    §4.7.4 pair, which shows the list governs the order.
    """
    reordered = dict(templates)
    reordered["comparison_judgment_priority"] = [
        "richer_set_of_ideas",
        "both_incoherent",
        "one_incoherent_other_not",
        "fewer_unjustified_themes",
        "more_abstract_rule",
        "neither_better",
    ]
    result = compare_answers_text(_dyz(), _xyd(), None, reordered)
    assert result["preferred"] == {"answer": "dyz", "reason": "richer_set_of_ideas"}
    assert result["verdict"].endswith("since it is based on a richer set of ideas.")


def test_the_prose_is_seed_data_not_python(templates):
    """Every phrase in the comparison comes from ``commentary_templates.json``, which is
    what the admin UI edits (§4.6: the program's English is "a flexible set of
    phrase-templates").

    Editing one phrase changes the sentence that uses it and nothing else.
    """
    edited = dict(templates)
    edited["comparison_templates"] = dict(templates["comparison_templates"])
    edited["comparison_templates"]["verdict"] = dict(
        templates["comparison_templates"]["verdict"]
    )
    edited["comparison_templates"]["verdict"]["reason_more_coherent"] = (
        ", because it holds together"
    )
    verdict = compare_answers_text(_dyz(), _xyd(), None, edited)["verdict"]
    assert verdict.endswith("is the better answer, because it holds together.")


def test_the_comparison_reads_the_same_in_both_voices(templates):
    """§4.6 footnote 16: "Turning off Eliza mode ... does not affect the commentary
    generated by the program when comparing different answers."  ``compare-answers``
    (``answers.ss:428-431``) passes one string for both voices."""
    result = compare_answers_text(_dyz(), _xyd(), None, templates)
    assert result["eliza_text"] == result["technical_text"] == result["text"]


# ---------------------------------------------------------------------------
# coherence-phrase  (answers.ss:919-926)
# ---------------------------------------------------------------------------


def test_coherence_bands_come_from_the_seed_data(templates):
    """``answers.ss:919-926``.  The Scheme defines the bands and calls them from
    nowhere; the thresholds line up with ``answer-incoherent?``'s 25-point gap
    (``answers.ss:916``) when the argument is rule abstractness minus theme
    abstractness, which is how :func:`coherence_score` computes it."""
    incoherent = _answer(
        ("abc", "abd", "xyz", "dyz"),
        {STRING_POSITION: "opposite"},
        rule_abstractness=20.0,
        theme_abstractness=90.0,
    )
    assert coherence_score(incoherent) == -70.0
    assert coherence_phrase(coherence_score(incoherent), templates) == "very incoherent"
    assert coherence_phrase(0.0, templates) == "very coherent"
    assert coherence_phrase(40.0, templates) == "coherent"
