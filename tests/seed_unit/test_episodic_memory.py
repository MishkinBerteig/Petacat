"""Reminding and comparison, which render against the phrasing in ``seed_data/``.

``compare_answers`` resolves the commentary templates when none are supplied, so the
distance calculation and the comparison both read what the seed data holds.
``find_remindings`` reaches the same code through ``distance``, and ``distance``'s
depth filter reads the shipped conceptual depths when no ``MetadataProvider`` supplies
them — so every figure below is a figure about the values Petacat ships with.
"""

import os

import pytest

from server.engine.memory import AnswerDescription, EpisodicMemory, SnagDescription

STRING_POSITION = "plato-string-position-category"
DIRECTION = "plato-direction-category"
GROUP_CATEGORY = "plato-group-category"
ALPHABETIC = "plato-alphabetic-position-category"
BOND_FACET = "plato-bond-facet"


def _answer(themes, *, quality=80.0, top_rule="top-rule"):
    return AnswerDescription(
        problem=("abc", "abd", "xyz", "xyd"),
        top_rule_description=top_rule,
        bottom_rule_description="",
        top_rule_quality=0.0,
        bottom_rule_quality=0.0,
        quality=quality,
        temperature=0.0,
        themes=themes,
        unjustified_slippages=[],
    )


# --- find_remindings -------------------------------------------------------

def test_find_remindings_excludes_the_query_answer_itself():
    mem = EpisodicMemory()
    desc = _answer({"direction": "opposite"})
    mem.store_answer(desc)
    # Querying with the very answer that is stored must not remind of itself.
    assert mem.find_remindings(desc, distance_threshold=5.0) == []


def test_find_remindings_returns_past_answer_within_threshold():
    mem = EpisodicMemory()
    past = _answer({"direction": "opposite", "position": "rightmost"})
    mem.store_answer(past)
    # One differing dimension, plus ``calculate-answer-distance``'s base of 1.
    query = _answer({"direction": "opposite", "position": "leftmost"})  # distance 2
    remindings = mem.find_remindings(query, distance_threshold=5.0)
    assert remindings == [past]


def test_find_remindings_excludes_past_answer_beyond_threshold():
    mem = EpisodicMemory()
    past = _answer({"direction": "same", "position": "leftmost"})
    mem.store_answer(past)
    query = _answer({"direction": "opposite", "position": "rightmost"})  # distance 3
    assert mem.find_remindings(query, distance_threshold=2.0) == []


def test_find_remindings_excludes_past_answer_at_exact_threshold():
    """At the threshold the activation is zero, and zero is not a reminding.

    ``memory.ss:212`` drives activation to 0 exactly *at* ``%distance-threshold%``,
    and ``memory.ss:214`` reports a reminding only when the activation exceeds 0.
    """
    mem = EpisodicMemory()
    past = _answer({"direction": "opposite"})
    mem.store_answer(past)
    query = _answer({"direction": "same"})  # distance exactly 2
    assert mem.find_remindings(query, distance_threshold=2.0) == []
    # One step inside the threshold it is remembered, with a graded activation.
    assert mem.find_remindings(query, distance_threshold=4.0) == [past]
    assert past.activation == 50.0


# --- distance: calculate-answer-distance (memory.ss:494-583) ---------------
#
# The Scheme's five components, and the weight each carries:
#
#   base                1                                        memory.ss:580
#   themes              differing-dimensions + 2*unique1 + 2*unique2   :552-555
#   top rule            2 * pairs that differ AND differ in depth      :556-571
#     or, when the clause lists will not align, round(|dA| / 10)       :568-570
#   justification       common ideas only one answer justified         :572-574
#   coherence           1 when the answers disagree about coherence    :575-578
#
# There is no bottom-rule term: memory.ss:558-559 passes get-top-rule-clauses twice.


def _rule(
    position="plato-rightmost",
    relation="plato-successor",
    literal=None,
    dimension="plato-letter-category",
):
    """One intrinsic clause in the shape ``rule_signature`` writes.

    ``rules.py:_clause_signature``: ``[clause_type, object_description, changes]``, where
    an object description is ``(object category, description type, descriptor)`` and a
    change is ``(dimension, from, to, relation)``.  ``_instantiate_change_template`` fills
    exactly one of ``to`` and ``relation`` — a relation for an abstract change, the
    literal node for a literal one — so the port writes across two slots what the Scheme
    keeps in one (``rules.ss:900-909``), and the other two arrive as ``None``.
    """
    return [
        [
            "intrinsic",
            ["plato-letter", "plato-string-position-category", position],
            [[dimension, None, literal, None if literal else relation]],
        ]
    ]


def _verbatim(letters):
    return [["verbatim", [f"plato-{letter}" for letter in letters]]]


def _described(
    problem,
    themes,
    *,
    unjustified=None,
    signature=None,
    bottom_signature=None,
    abstractness=50.0,
    bottom_abstractness=50.0,
    theme_abstractness=0.0,
    rule="the rule",
):
    return AnswerDescription(
        problem=problem,
        top_rule_description=rule,
        bottom_rule_description="",
        top_rule_quality=70.0,
        bottom_rule_quality=70.0,
        quality=70.0,
        temperature=30.0,
        themes=dict(themes),
        unjustified_slippages=[],
        unjustified_themes=dict(unjustified or {}),
        top_rule_signature=signature,
        bottom_rule_signature=bottom_signature,
        top_rule_abstractness=abstractness,
        bottom_rule_abstractness=bottom_abstractness,
        theme_abstractness=theme_abstractness,
    )


#: The crosswise reading of ``abc -> abd``, which two different problems can share.
_CROSSWISE = {
    STRING_POSITION: "opposite",
    DIRECTION: "opposite",
    ALPHABETIC: "opposite",
}

#: The two answers of §4.7.4, Table 4.2.  Their theme patterns are the dissertation's;
#: neither fixture records a clause list, which is what sends the rule term to its
#: abstractness fallback below.  Built fresh per use: ``find_remindings`` writes an
#: activation onto the description it is given.
def _xyd():
    return _described(
        ("abc", "abd", "xyz", "xyd"),
        {
            STRING_POSITION: "identity",
            DIRECTION: "identity",
            GROUP_CATEGORY: "identity",
        },
        abstractness=60.0,
        theme_abstractness=30.0,
    )


def _dyz():
    return _described(
        ("abc", "abd", "xyz", "dyz"),
        {
            STRING_POSITION: "opposite",
            DIRECTION: "opposite",
            GROUP_CATEGORY: "opposite",
            ALPHABETIC: "opposite",
        },
        abstractness=20.0,
        theme_abstractness=70.0,
    )


@pytest.mark.parametrize(
    "answer_a, answer_b, expected",
    [
        # One interpretation, two problems.  Nothing differs anywhere, so only the
        # base survives:  1 + 0 + 0 + 0 + 0 = 1.
        pytest.param(
            _described(("abc", "abd", "xyz", "wyz"), _CROSSWISE, signature=_rule()),
            _described(("rst", "rsu", "xyz", "wyz"), _CROSSWISE, signature=_rule()),
            1.0,
            id="one_interpretation_two_problems",
        ),
        # leftmost against rightmost.  One concept pair differs, and both concepts sit
        # at conceptual depth 40, so ``num-rule-differences`` filters it out
        # (memory.ss:562-564):  1 + 0 + 2*0 + 0 + 0 = 1.  The rules are different
        # rules; they are not rules pitched at different levels.
        pytest.param(
            _described(("abc", "abd", "xyz", "wyz"), _CROSSWISE, signature=_rule()),
            _described(
                ("abc", "abd", "xyz", "wyz"),
                _CROSSWISE,
                signature=_rule(position="plato-leftmost"),
            ),
            1.0,
            id="leftmost_vs_rightmost_costs_nothing",
        ),
        # Two literal rules naming different letters.  Every letter node is at depth
        # 10, so the pair is filtered:  1 + 0 + 2*0 + 0 + 0 = 1.
        pytest.param(
            _described(
                ("abc", "abd", "xyz", "wyz"),
                _CROSSWISE,
                signature=_rule(literal="plato-d"),
            ),
            _described(
                ("abc", "abd", "xyz", "wyz"),
                _CROSSWISE,
                signature=_rule(literal="plato-k"),
            ),
            1.0,
            id="different_letters_cost_nothing",
        ),
        # §4.7.4's rule contrast: an abstract change (``plato-successor``, depth 50)
        # against the literal one it was substituted for (``plato-d``, depth 10).  The
        # Scheme keeps both in one descriptor slot, so they line up as a single pair
        # and the depths differ:  1 + 0 + 2*1 + 0 + 0 = 3.
        pytest.param(
            _described(("abc", "abd", "xyz", "wyz"), _CROSSWISE, signature=_rule()),
            _described(
                ("abc", "abd", "xyz", "wyz"),
                _CROSSWISE,
                signature=_rule(literal="plato-d"),
            ),
            3.0,
            id="an_abstract_rule_against_the_literal_one",
        ),
        # successor (50) against sameness (80):  one surviving pair.
        #   1 + 0 + 2*1 + 0 + 0 = 3.
        pytest.param(
            _described(("abc", "abd", "xyz", "wyz"), _CROSSWISE, signature=_rule()),
            _described(
                ("abc", "abd", "xyz", "wyz"),
                _CROSSWISE,
                signature=_rule(relation="plato-sameness"),
            ),
            3.0,
            id="one_pair_differing_in_depth",
        ),
        # letter-category (30) against length (60), and successor (50) against
        # sameness (80):  two surviving pairs.  1 + 0 + 2*2 + 0 + 0 = 5 — exactly the
        # reminding threshold, so this pair does *not* come to mind.
        pytest.param(
            _described(("abc", "abd", "xyz", "wyz"), _CROSSWISE, signature=_rule()),
            _described(
                ("abc", "abd", "xyz", "wyz"),
                _CROSSWISE,
                signature=_rule(relation="plato-sameness", dimension="plato-length"),
            ),
            5.0,
            id="two_pairs_differing_in_depth",
        ),
        # An intrinsic rule against a verbatim one.  ``traverse-rule-clauses`` fails on
        # the clause-type symbols, so there is nothing to count and abstractness stands
        # in:  1 + 0 + round(|60 - 10| / 10) + 0 + 0 = 1 + 5 = 6.
        pytest.param(
            _described(
                ("abc", "abd", "xyz", "wyz"),
                _CROSSWISE,
                signature=_rule(),
                abstractness=60.0,
            ),
            _described(
                ("abc", "abd", "xyz", "wyz"),
                _CROSSWISE,
                signature=_verbatim("wyz"),
                abstractness=10.0,
            ),
            6.0,
            id="incomparable_rules_fall_back_to_abstractness",
        ),
        # Two different verbatim rules: compared whole, so incomparable, so the
        # fallback again — and 25/10 is a tie, which Chez's ``round`` and Python's both
        # break to even:  1 + 0 + round(2.5) + 0 + 0 = 1 + 2 = 3.
        pytest.param(
            _described(
                ("abc", "abd", "xyz", "wyz"),
                _CROSSWISE,
                signature=_verbatim("wyz"),
                abstractness=45.0,
            ),
            _described(
                ("abc", "abd", "xyz", "xyd"),
                _CROSSWISE,
                signature=_verbatim("xyd"),
                abstractness=20.0,
            ),
            3.0,
            id="abstractness_fallback_rounds_ties_to_even",
        ),
        # The bottom rules disagree as loudly as two rules can — different shapes,
        # 80 points of abstractness apart — and contribute nothing, because
        # memory.ss:558-559 never looks at them:  1 + 0 + 0 + 0 + 0 = 1.
        pytest.param(
            _described(
                ("abc", "abd", "xyz", "wyz"),
                _CROSSWISE,
                signature=_rule(),
                bottom_signature=_rule(relation="plato-sameness"),
                bottom_abstractness=90.0,
            ),
            _described(
                ("abc", "abd", "xyz", "wyz"),
                _CROSSWISE,
                signature=_rule(),
                bottom_signature=_verbatim("wyz"),
                bottom_abstractness=10.0,
            ),
            1.0,
            id="the_bottom_rules_are_not_compared",
        ),
        # One differing dimension (String-Position) and one theme the other answer does
        # not mention at all (Alphabetic-Position):
        #   1 + (1 + 2*0 + 2*1) + 0 + 0 + 0 = 4.  Inside the threshold of 5.
        pytest.param(
            _described(
                ("abc", "abd", "xyz", "xyd"),
                {STRING_POSITION: "identity", DIRECTION: "identity"},
                signature=_rule(),
            ),
            _described(
                ("abc", "abd", "xyz", "wyz"),
                {
                    STRING_POSITION: "opposite",
                    DIRECTION: "identity",
                    ALPHABETIC: "opposite",
                },
                signature=_rule(),
            ),
            4.0,
            id="a_differing_dimension_counts_once_a_unique_theme_twice",
        ),
        # The same crosswise themes in two problems, one read through a literal top
        # rule and the other through an abstract one.  ``answer-incoherent?`` fires for
        # the first (70 > 50, 20 < 70, and the 50-point gap exceeds 25) and not for the
        # second (the gap is 10), so the answers disagree about coherence:  +1.
        # The rules differ only leftmost-against-rightmost, so the pair count is 0 and
        # the 40 points of abstractness between them are never consulted — the
        # fallback is the pair count's *alternative*, not an extra term:
        #   1 + 0 + 2*0 + 0 + 1 = 2.
        pytest.param(
            _described(
                ("abc", "abd", "xyz", "wyz"),
                _CROSSWISE,
                signature=_rule(),
                abstractness=20.0,
                theme_abstractness=70.0,
            ),
            _described(
                ("rst", "rsu", "xyz", "wyz"),
                _CROSSWISE,
                signature=_rule(position="plato-leftmost"),
                abstractness=60.0,
                theme_abstractness=70.0,
            ),
            2.0,
            id="a_coherence_mismatch_costs_one",
        ),
        # §4.7.4, Table 4.2.  Themes: String-Position, Direction and Group-Category are
        # all held by both answers with opposed relations (3 differing dimensions),
        # and dyz alone sees an alphabetic-position reversal (1 unique theme):
        #   3 + 2*0 + 2*1 = 5.
        # Rules: neither fixture records a clause list, so the abstractness fallback
        # applies: round(|60 - 20| / 10) = 4.
        # Coherence: xyd's themes are literal enough for its rule; dyz's are 50 points
        # more abstract than its rule, which is §4.7.3's "dissonance": +1.
        #   1 + 5 + 4 + 0 + 1 = 11 — far outside the threshold of 5.
        pytest.param(_xyd(), _dyz(), 11.0, id="the_dissertations_xyd_against_dyz"),
    ],
)
def test_distance_is_the_scheme_arithmetic(answer_a, answer_b, expected):
    memory = EpisodicMemory()
    assert memory.distance(answer_a, answer_b) == expected
    # ``calculate-answer-distance`` is symmetric in everything it sums.
    assert memory.distance(answer_b, answer_a) == expected


def test_the_threshold_admits_the_near_pair_and_refuses_the_dissertations_pair():
    """The distance function's calibration *is* the reminding mechanism.

    ``%distance-threshold%`` is 5 (``memory.ss:488``) and ``memory.ss:212`` drives
    activation to zero at it, so a pair at 4 comes to mind at strength 20 and the pair
    §4.7.4 spends four pages contrasting does not come to mind at all.
    """
    memory = EpisodicMemory()
    near = _described(
        ("abc", "abd", "xyz", "xyd"),
        {STRING_POSITION: "identity", DIRECTION: "identity"},
        signature=_rule(),
    )
    far = _dyz()
    memory.store_answer(near)
    memory.store_answer(far)

    query = _described(
        ("abc", "abd", "xyz", "wyz"),
        {STRING_POSITION: "opposite", DIRECTION: "identity", ALPHABETIC: "opposite"},
        signature=_rule(),
    )
    assert memory.find_remindings(query, distance_threshold=5.0) == [near]
    # 100 * (1 - 4/5), in binary floating point.
    assert near.activation == pytest.approx(20.0)
    assert far.activation == 0.0


def test_a_snag_justified_theme_leaves_the_justification_component():
    """§4.7.3's ``aaabccc`` / ``aaabaaa`` pair, as a distance.

    ``get-snag-justified-themes`` (``answers.ss:285-299``) is subtracted from an
    answer's unjustified themes *before* the justification component counts them
    (``memory.ss:506-513``), so an idea one answer justified by avoiding a snag and the
    other could not justify at all is a real difference between them:

        1 + themes 0 + rule 0 + justification 1 + coherence 0 = 2

    Comparing the dimension key sets instead — ``{bond-facet} - {bond-facet}`` — makes
    the component vanish and the two answers measure 1 apart, indistinguishable from a
    pair that agrees about everything.
    """
    memory = EpisodicMemory()
    rule = "Swap letter-categories of all objects in string"
    with_snag = _described(
        ("eqe", "qeq", "abbbc", "aaabccc"),
        {STRING_POSITION: "identity"},
        unjustified={BOND_FACET: "diff"},
        signature=_rule(),
        rule=rule,
    )
    without_snag = _described(
        ("eqe", "qeq", "abbba", "aaabaaa"),
        {STRING_POSITION: "identity"},
        unjustified={BOND_FACET: "diff"},
        signature=_rule(),
        rule=rule,
    )
    memory.store_snag(
        SnagDescription(
            problem=("eqe", "qeq", "abbbc"),
            codelet_count=500,
            temperature=40.0,
            theme_pattern={STRING_POSITION: "identity"},
            description=rule,
            # ``get-equivalent-snag`` (``memory.ss:84-89``) matches on the rule's
            # *clause list*, not its prose, so the snag has to carry the same
            # signature the answer does for the episodes to be the same episode.
            rule_signature=_rule(),
        )
    )

    assert memory.distance(with_snag, without_snag) == 2.0


def test_an_unjustified_theme_on_a_differing_dimension_is_not_charged_twice():
    """``memory.ss:548-551`` removes the differing themes from the justification
    component.

    A dimension the two answers already disagree about has been paid for once, as a
    differing dimension; charging it again because one side could not justify its half
    counts the same disagreement twice:

        1 + themes 1 + rule 0 + justification 0 + coherence 0 = 2
    """
    memory = EpisodicMemory()
    a = _described(
        ("abc", "abd", "xyz", "xyd"),
        {},
        unjustified={STRING_POSITION: "identity"},
        signature=_rule(),
    )
    b = _described(
        ("abc", "abd", "xyz", "wyz"),
        {STRING_POSITION: "opposite"},
        signature=_rule(),
    )
    assert memory.distance(a, b) == 2.0


def test_two_identical_answers_are_zero_apart():
    """``memory.ss:496-497``, guarding the invariant stated at ``memory.ss:490-493``."""
    memory = EpisodicMemory()
    one = _described(("abc", "abd", "xyz", "wyz"), _CROSSWISE, signature=_rule())
    other = _described(("abc", "abd", "xyz", "wyz"), _CROSSWISE, signature=_rule())
    assert memory.distance(one, other) == 0.0


# --- compare_answers -------------------------------------------------------

def test_compare_answers_reports_shared_theme_with_equal_value():
    mem = EpisodicMemory()
    a = _answer({"position": "rightmost"})
    b = _answer({"position": "rightmost"})
    result = mem.compare_answers(a, b)
    assert result["common_themes"] == {"position": "rightmost"}


def test_compare_answers_splits_dimension_with_differing_values():
    mem = EpisodicMemory()
    a = _answer({"direction": "opposite"})
    b = _answer({"direction": "same"})
    result = mem.compare_answers(a, b)
    # Same category, different relation -> a *differing* theme, not two uniques.
    assert result["differing_themes"]["direction"] == ("opposite", "same")


def test_compare_answers_reports_dimension_present_only_in_a():
    mem = EpisodicMemory()
    a = _answer({"position": "rightmost", "direction": "opposite"})
    b = _answer({"position": "rightmost"})
    result = mem.compare_answers(a, b)
    assert result["a_unique_themes"] == {"direction": "opposite"}


def test_compare_answers_includes_quality_and_rule_fields():
    mem = EpisodicMemory()
    a = _answer({"position": "rightmost"}, quality=80.0, top_rule="rule-a")
    b = _answer({"position": "rightmost"}, quality=55.0, top_rule="rule-b")
    result = mem.compare_answers(a, b)
    assert result["a_quality"] == 80.0
    assert result["b_quality"] == 55.0
    assert result["a_rule"] == "rule-a"
    assert result["b_rule"] == "rule-b"


# --- snag identity: memory.ss:78-89, 289-291, 336-340 ----------------------
#
# ``make-snag-description`` stores the rule's *clause list*, and ``equal?`` compares
# the three problem strings plus ``rule-clause-lists-equal?``.  The English
# transcription cannot stand in for it, for the two reasons ``rules.py:rule_signature``
# already documents on the answer side.


@pytest.fixture(scope="module")
def nodes():
    from server.engine.metadata import MetadataProvider
    from server.engine.slipnet import Slipnet

    seed_dir = os.path.join(os.path.dirname(__file__), "..", "..", "seed_data")
    return Slipnet.from_metadata(MetadataProvider.from_seed_data(seed_dir)).nodes


def _real_rule(nodes, position="plato-rightmost", relation="plato-successor"):
    """A real one-clause rule: "change letter-category of the <position> letter by <r>"."""
    from server.engine.rules import CLAUSE_INTRINSIC, RULE_TOP, Rule, RuleChange, RuleClause

    clause = RuleClause(
        clause_type=CLAUSE_INTRINSIC,
        object_description=(
            nodes["plato-letter"],
            nodes["plato-string-position-category"],
            nodes[position],
        ),
        changes=[
            RuleChange(
                dimension=nodes["plato-letter-category"], relation=nodes[relation]
            )
        ],
    )
    return Rule(rule_type=RULE_TOP, clauses=[clause])


def _changeless_rule(nodes, position="plato-rightmost"):
    """A clause with no changes — the shape that transcribes to "Unknown transformation"."""
    from server.engine.rules import CLAUSE_INTRINSIC, RULE_TOP, Rule, RuleClause

    clause = RuleClause(
        clause_type=CLAUSE_INTRINSIC,
        object_description=(
            nodes["plato-letter"],
            nodes["plato-string-position-category"],
            nodes[position],
        ),
        changes=[],
    )
    return Rule(rule_type=RULE_TOP, clauses=[clause])


def _snag_for(rule, problem=("abc", "abd", "xyz")):
    from server.engine.rules import rule_signature

    return SnagDescription(
        problem=problem,
        codelet_count=100,
        temperature=100.0,
        theme_pattern={},
        description=rule.transcribe_to_english(),
        rule_signature=rule_signature(rule),
    )


def test_snag_present_matches_the_same_rule_on_the_same_problem(nodes):
    """``snag-present?`` (``memory.ss:78-83``) — the guard that keeps one impasse from
    being recorded twice."""
    memory = EpisodicMemory()
    memory.store_snag(_snag_for(_real_rule(nodes)))
    assert memory.snag_present(("abc", "abd", "xyz"), _real_rule(nodes)) is True


def test_two_structurally_different_rules_with_identical_prose_do_not_collide(nodes):
    """The first of the two collisions a prose comparison has.

    ``transcribe_to_english`` renders the *changes* and says nothing about which object
    a clause names, so "change the leftmost letter by successor" and "change the
    rightmost letter by successor" come out as the same sentence.  As prose they were
    one snag episode; as clause lists they are two.
    """
    memory = EpisodicMemory()
    rightmost = _real_rule(nodes, position="plato-rightmost")
    leftmost = _real_rule(nodes, position="plato-leftmost")
    assert rightmost.transcribe_to_english() == leftmost.transcribe_to_english()

    memory.store_snag(_snag_for(rightmost))
    assert memory.snag_present(("abc", "abd", "xyz"), leftmost) is False


def test_two_untranscribable_rules_do_not_collide(nodes):
    """The second: every rule that fails to transcribe reads "Unknown transformation",
    so under a prose comparison the first such snag matched *every* later one and no
    further impasse was ever recorded.  ``rules.py:rule_signature`` documents exactly
    this hazard for answers; the snag path had it open."""
    memory = EpisodicMemory()
    first = _changeless_rule(nodes, position="plato-rightmost")
    second = _changeless_rule(nodes, position="plato-leftmost")
    assert first.transcribe_to_english() == "Unknown transformation"
    assert second.transcribe_to_english() == "Unknown transformation"

    memory.store_snag(_snag_for(first))
    assert memory.snag_present(("abc", "abd", "xyz"), second) is False
    assert memory.snag_present(("abc", "abd", "xyz"), first) is True


def test_a_snag_with_no_recorded_clause_list_matches_nothing(nodes):
    """A null signature means the clause list was never captured, not that the rule was
    empty — the same reservation ``_answers_equal`` makes for an answer."""
    memory = EpisodicMemory()
    memory.store_snag(
        SnagDescription(
            problem=("abc", "abd", "xyz"),
            codelet_count=100,
            temperature=100.0,
            theme_pattern={},
            description="change LettCtgy by succ",
        )
    )
    assert memory.snag_present(("abc", "abd", "xyz"), _real_rule(nodes)) is False


def test_get_equivalent_snag_matches_on_the_clause_list(nodes):
    """``get-equivalent-snag`` (``memory.ss:84-89``) passes the answer's *top-rule
    clauses*, which is what §4.7.3's snag-justified distinction rests on."""
    from server.engine.rules import rule_signature

    memory = EpisodicMemory()
    rule = _real_rule(nodes)
    snag = _snag_for(rule)
    memory.store_snag(snag)

    answer = _described(
        ("abc", "abd", "xyz", "xyd"), {}, signature=rule_signature(rule)
    )
    assert memory.get_equivalent_snag(answer) is snag

    other = _described(
        ("abc", "abd", "xyz", "xyd"),
        {},
        signature=rule_signature(_real_rule(nodes, position="plato-leftmost")),
    )
    assert memory.get_equivalent_snag(other) is None


def test_a_snag_on_another_problem_is_a_different_episode(nodes):
    memory = EpisodicMemory()
    memory.store_snag(_snag_for(_real_rule(nodes), problem=("abc", "abd", "mrrjjj")))
    assert memory.snag_present(("abc", "abd", "xyz"), _real_rule(nodes)) is False


# --- clear_activations: run.ss:212 ----------------------------------------


def test_clear_activations_zeroes_every_stored_answer():
    """``init-mcat`` clears them at the start of every run (``run.ss:212``): an
    activation says how strongly *this* run is reminded of a past answer, so a new run
    of a Training Session starts reminded of nothing."""
    memory = EpisodicMemory()
    past = _answer({"direction": "opposite"})
    memory.store_answer(past)
    memory.find_remindings(_answer({"direction": "opposite"}), distance_threshold=5.0)
    assert past.activation > 0.0

    memory.clear_activations()
    assert past.activation == 0.0
