"""Rule quality against the Scheme's three subformulas, hand-computed.

``compute-rule-quality`` (``rules.ss:1544-1549``) is

    round( (uniformity/100) * weighted-average([abstractness, succinctness], [3, 2]) )

and each of the three inputs has its own shape:

* ``compute-rule-uniformity`` (``rules.ss:1552-1596``) — three terms at weights
  5, 5 and 1, squashed by ``exp(4(x-1))``.  The intrinsic term is the mean of the
  **product** over conceptual dimensions of ``2|p-½|`` and the object-attribute
  homogeneity; the extrinsic term is the mean of each extrinsic clause's
  **cubed** attribute homogeneity; the third is how far the rule is from mixing
  clause kinds.  ObjCtgy and BondFacet changes are excluded from the first.
* ``compute-rule-abstractness`` (``rules.ss:1599-1625``) — ``sigmoid(3, 40)`` of
  the mean of up to three **per-category** averages, empty categories dropped.
* ``compute-rule-succinctness`` (``rules.ss:1628-1637``) — ``100·4/(3 + cost)``,
  an intrinsic clause costing 1 and an extrinsic clause 2 only when it names more
  than one object.

The expectations below are worked out by hand from those formulas and the
conceptual depths Petacat ships, so they check the port rather than restating it.
"""

import math
import os

import pytest

from server.engine.metadata import MetadataProvider
from server.engine.rules import (
    CLAUSE_EXTRINSIC,
    CLAUSE_INTRINSIC,
    CLAUSE_VERBATIM,
    RULE_TOP,
    Rule,
    RuleChange,
    RuleClause,
)
from server.engine.slipnet import Slipnet

SEED_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "seed_data")


@pytest.fixture(scope="module")
def meta():
    return MetadataProvider.from_seed_data(SEED_DIR)


@pytest.fixture(scope="module")
def nodes(meta):
    return Slipnet.from_metadata(meta).nodes


def _od(nodes, object_type, attribute, descriptor):
    return (nodes[object_type], nodes[attribute], nodes[descriptor])


def _intrinsic(nodes, descriptor_position, dimension, descriptor, relation=False):
    """One intrinsic clause: "change <dimension> of the <position> letter to <d>"."""
    change = (
        RuleChange(dimension=nodes[dimension], relation=nodes[descriptor])
        if relation
        else RuleChange(dimension=nodes[dimension], to_descriptor=nodes[descriptor])
    )
    return RuleClause(
        clause_type=CLAUSE_INTRINSIC,
        object_description=_od(
            nodes, "plato-letter", "plato-string-position-category", descriptor_position
        ),
        changes=[change],
    )


def _quality(rule, meta):
    rule.compute_quality(meta)
    return (rule.uniformity, rule.abstractness, rule.succinctness, rule.quality)


# ── the three depths every expectation below is built from ──────────────────


def test_the_depths_the_expectations_rest_on(nodes):
    """If these move, every hand-computed number in this file moves with them."""
    assert nodes["plato-string-position-category"].conceptual_depth == 70
    assert nodes["plato-letter-category"].conceptual_depth == 30
    assert nodes["plato-successor"].conceptual_depth == 50
    assert nodes["plato-d"].conceptual_depth == 10


# ── verbatim: the finding's headline number ─────────────────────────────────


def test_a_verbatim_rule_scores_forty(nodes, meta):
    """``round((0*3 + 100*2)/5) = 40`` — not 10.

    ``rules.ss:1554`` and ``:1630`` give a verbatim rule uniformity and
    succinctness 100, ``:1604`` gives it abstractness 0, and ``compute-rule-quality``
    runs over it like any other rule.  Petacat hard-coded **10**, which is
    ``compute-rule-intrinsic-quality``'s verbatim constant (``rules.ss:1662``) — a
    different quantity that nothing in the answer path reads.  The 30-point gap is
    a rule's whole standing in the answer-finder's pick.
    """
    rule = Rule(
        RULE_TOP,
        [RuleClause(clause_type=CLAUSE_VERBATIM, verbatim_letters=[nodes["plato-a"]])],
    )
    assert _quality(rule, meta) == (100.0, 0.0, 100.0, 40)


def test_the_identity_rule_scores_a_hundred(meta):
    """``rules.ss:1554, 1603, 1631`` — a rule with no clauses changes nothing."""
    rule = Rule(RULE_TOP, [])
    assert _quality(rule, meta) == (100.0, 100.0, 100.0, 100.0)


# ── single intrinsic clauses ────────────────────────────────────────────────


def test_one_abstract_intrinsic_clause(nodes, meta):
    """"Change the letter-category of the rightmost letter to its successor".

    uniformity: one dimension, all-relation, so ``2|1-½| = 1``; one attribute, so
    homogeneity 1; ``average(1, 1) = 1``.  No extrinsic clauses, so that term is 1,
    and the clause-type term is 1/1.  ``exp(4(1-1)) = 1`` → **100**.

    abstractness: attributes average 70 (String-Position), change descriptors
    average 50 (successor), no swap dimensions.  ``mean(70, 50) = 60`` and
    ``sigmoid(3,40)(60) = 1/(1+e^-2.4) = 0.91683`` → **92**.

    succinctness: one intrinsic clause costs 1, so ``100·4/4`` → **100**.

    quality: ``round(1.0 · (3·92 + 2·100)/5) = round(95.2)`` → **95**.
    """
    rule = Rule(
        RULE_TOP,
        [
            _intrinsic(
                nodes, "plato-rightmost", "plato-letter-category",
                "plato-successor", relation=True,
            )
        ],
    )
    assert _quality(rule, meta) == (100.0, 92.0, 100.0, 95)


def test_one_literal_intrinsic_clause(nodes, meta):
    """The same rule stated literally — "…to ``d``" — is markedly less abstract.

    abstractness: ``mean(70, 10) = 40``, and 40 is the sigmoid's midpoint, so
    exactly **50**.  quality: ``round((3·50 + 2·100)/5) = 70``.

    §3.3.5 introduces abstractness with precisely this comparison, which is why
    the change *descriptor*'s depth has to be what is measured: using the
    dimension's depth would score both rules identically.
    """
    rule = Rule(
        RULE_TOP,
        [_intrinsic(nodes, "plato-rightmost", "plato-letter-category", "plato-d")],
    )
    assert _quality(rule, meta) == (100.0, 50.0, 100.0, 70)


# ── several clauses: where the restructured subformulas bite ────────────────


def test_three_literal_clauses_are_uniform_but_verbose(nodes, meta):
    """"leftmost→q, middle→e, rightmost→q" — the literal reading of ``eqe -> qeq``.

    uniformity is still 100: all three changes are on one dimension and all
    literal, and all three object-descriptions use String-Position.

    succinctness: three intrinsic clauses cost 3, so ``100·4/6 = 66.67`` → **67**.
    Under the old cost table this rule scored the same, but a clause whose changes
    were all on *components* cost 0.5, which let succinctness reach 114 — above the
    100 the formula's own numerator caps it at.

    quality: ``round(1.0 · (3·50 + 2·67)/5) = round(56.8)`` → **57**.
    """
    rule = Rule(
        RULE_TOP,
        [
            _intrinsic(nodes, "plato-leftmost", "plato-letter-category", "plato-q"),
            _intrinsic(nodes, "plato-middle", "plato-letter-category", "plato-e"),
            _intrinsic(nodes, "plato-rightmost", "plato-letter-category", "plato-q"),
        ],
    )
    assert _quality(rule, meta) == (100.0, 50.0, 67.0, 57)


def test_a_mixed_relation_and_literal_rule_loses_uniformity(nodes, meta):
    """One change by successor and one to ``d``, both Letter-Category.

    §3.3.5: "there should be pressure to describe the changes in a uniform way —
    either all in terms of abstract relationships … or all in terms of literal
    descriptors".  One dimension holding one of each gives ``p = ½`` and so
    ``2|½-½| = 0``; the product over dimensions is therefore 0 and the intrinsic
    term is ``average(0, 1) = ½``.

    raw = ``(5·0.5 + 5·1 + 1·1)/11 = 8.5/11 = 0.77273``; ``exp(4(0.77273-1)) =
    exp(-0.90909) = 0.40289`` → uniformity **40**.

    abstractness: attributes 70, descriptors ``mean(50, 10) = 30``;
    ``mean(70, 30) = 50`` and ``sigmoid(3,40)(50) = 1/(1+e^-1.2) = 0.76852`` → **77**.
    succinctness: two intrinsic clauses → ``100·4/5`` = **80**.
    quality: ``round(0.40 · (3·77 + 2·80)/5) = round(0.4 · 78.2) = round(31.28)``
    → **31**.

    The old formula scored the same mix as an unweighted mean of ad-hoc
    homogeneity factors and never took the product over dimensions, so a rule that
    mixed its idioms was penalised far less than the reference penalises it.
    """
    rule = Rule(
        RULE_TOP,
        [
            _intrinsic(
                nodes, "plato-leftmost", "plato-letter-category",
                "plato-successor", relation=True,
            ),
            _intrinsic(nodes, "plato-rightmost", "plato-letter-category", "plato-d"),
        ],
    )
    uniformity, abstractness, succinctness, quality = _quality(rule, meta)
    assert (uniformity, abstractness, succinctness) == (40.0, 77.0, 80.0)
    assert quality == 31
    # The squash is not an approximation of the mean; it is the mean put through
    # exp(4(x-1)), which is what turns a modest mixture into a large penalty.
    assert uniformity == round(100.0 * math.exp(4 * (8.5 / 11 - 1)))


def test_object_category_changes_are_excluded_from_uniformity(nodes, meta):
    """``rules.ss:1560-1564`` drops ObjCtgy and BondFacet changes before measuring.

    Neither is ever a matter of style: an ObjCtgy change says a group became a
    letter, and a BondFacet "change" carries no effect at all (``rules.ss:1386``).
    Counting them would let a rule's uniformity be decided by bookkeeping.  Here
    the literal ObjCtgy:letter change sits beside a relational Letter-Category one;
    were it counted the dimension mix would drag uniformity down, and it does not.
    """
    clause = RuleClause(
        clause_type=CLAUSE_INTRINSIC,
        object_description=_od(
            nodes, "plato-group", "plato-string-position-category", "plato-rightmost"
        ),
        changes=[
            RuleChange(
                dimension=nodes["plato-letter-category"],
                relation=nodes["plato-successor"],
            ),
            RuleChange(
                dimension=nodes["plato-object-category"],
                to_descriptor=nodes["plato-letter"],
            ),
        ],
    )
    rule = Rule(RULE_TOP, [clause])
    assert rule_uniformity(rule, meta) == 100.0


def rule_uniformity(rule, meta):
    rule.compute_quality(meta)
    return rule.uniformity


# ── extrinsic clauses: dead until RU-1, and measured differently ────────────


def test_a_one_object_swap_clause(nodes, meta):
    """"Swap the letter-categories of the components of the whole string".

    uniformity: no intrinsic clauses → that term is 1; one extrinsic clause with
    one object-description → homogeneity 1, cubed 1; clause-type 1/1 → **100**.

    abstractness: attributes average 70 (String-Position), no intrinsic changes so
    that category is dropped, swap dimensions average 30 (Letter-Category);
    ``mean(70, 30) = 50`` → **77**.

    succinctness: an extrinsic clause naming one object costs 1 (``rules.ss:1636``),
    so ``100·4/4`` → **100**.  quality ``round((3·77 + 2·100)/5) = round(86.2)``
    → **86**.
    """
    clause = RuleClause(
        clause_type=CLAUSE_EXTRINSIC,
        object_description=(
            "string",
            nodes["plato-string-position-category"],
            nodes["plato-whole"],
        ),
        dimensions=[nodes["plato-letter-category"]],
    )
    rule = Rule(RULE_TOP, [clause])
    assert _quality(rule, meta) == (100.0, 77.0, 100.0, 86)


def test_a_three_object_swap_clause_costs_two(nodes, meta):
    """Naming the objects individually is the more verbose way to say it.

    Same uniformity and abstractness as the one-object form; succinctness is
    ``100·4/5`` = **80** because ``(> (length (2nd rule-clause)) 1)``
    (``rules.ss:1635``).  quality ``round((3·77 + 2·80)/5) = round(78.2)`` → **78**.
    """
    clause = RuleClause(
        clause_type=CLAUSE_EXTRINSIC,
        extrinsic_objects=[
            _od(nodes, "plato-letter", "plato-string-position-category", "plato-leftmost"),
            _od(nodes, "plato-letter", "plato-string-position-category", "plato-middle"),
            _od(nodes, "plato-letter", "plato-string-position-category", "plato-rightmost"),
        ],
        dimensions=[nodes["plato-letter-category"]],
    )
    rule = Rule(RULE_TOP, [clause])
    assert _quality(rule, meta) == (100.0, 77.0, 80.0, 78)


def test_a_swap_clause_with_mixed_attributes_is_cubed(nodes, meta):
    """``(compose ^3 object-description-uniformity)`` — ``rules.ss:1582``.

    Two of the three object-descriptions use String-Position and one uses
    Letter-Category, so homogeneity is 2/3 and the extrinsic term is
    ``(2/3)^3 = 0.29630``.  raw = ``(5·1 + 5·0.29630 + 1·1)/11 = 0.68013``;
    ``exp(4(0.68013-1)) = exp(-1.27946) = 0.27818`` → uniformity **28**.

    The cube is what makes a swap stated in mismatched terms collapse rather than
    merely dip: without it the extrinsic term would be 2/3, raw ``0.84848`` and
    uniformity 54 — nearly twice as forgiving.
    """
    clause = RuleClause(
        clause_type=CLAUSE_EXTRINSIC,
        extrinsic_objects=[
            _od(nodes, "plato-letter", "plato-string-position-category", "plato-leftmost"),
            _od(nodes, "plato-letter", "plato-string-position-category", "plato-rightmost"),
            _od(nodes, "plato-letter", "plato-letter-category", "plato-b"),
        ],
        dimensions=[nodes["plato-letter-category"]],
    )
    rule = Rule(RULE_TOP, [clause])
    assert rule_uniformity(rule, meta) == 28.0
    assert rule_uniformity(rule, meta) == round(
        100.0 * math.exp(4 * ((5 + 5 * (2 / 3) ** 3 + 1) / 11 - 1))
    )


def test_mixing_clause_kinds_costs_the_third_term(nodes, meta):
    """One intrinsic clause and one extrinsic clause: clause-type uniformity 1/2.

    Both other terms are 1, so raw = ``(5 + 5 + 0.5)/11 = 0.95455`` and
    ``exp(4(0.95455-1)) = exp(-0.18182) = 0.83376`` → **83**.  Weight 1 against 5
    and 5: the reference cares much less about mixing kinds than about mixing
    idioms within a kind, which is exactly what the 5/5/1 split says.
    """
    rule = Rule(
        RULE_TOP,
        [
            _intrinsic(
                nodes, "plato-rightmost", "plato-letter-category",
                "plato-successor", relation=True,
            ),
            RuleClause(
                clause_type=CLAUSE_EXTRINSIC,
                object_description=(
                    "string",
                    nodes["plato-string-position-category"],
                    nodes["plato-whole"],
                ),
                dimensions=[nodes["plato-letter-category"]],
            ),
        ],
    )
    assert rule_uniformity(rule, meta) == 83.0


def test_the_swap_dimension_is_an_abstractness_category_of_its_own(nodes, meta):
    """``rules.ss:1610-1611, 1618-1619`` averages swap dimensions separately.

    Swapping on Length (depth 60) rather than Letter-Category (depth 30) makes the
    same clause more abstract: ``mean(70, 60) = 65`` and
    ``sigmoid(3,40)(65) = 1/(1+e^-3.0) = 0.95257`` → **95**, against the 77 the
    Letter-Category form scores.  This factor was dead code before RU-1 restored
    the clause's dimensions.
    """
    clause = RuleClause(
        clause_type=CLAUSE_EXTRINSIC,
        object_description=(
            "string",
            nodes["plato-string-position-category"],
            nodes["plato-whole"],
        ),
        dimensions=[nodes["plato-length"]],
    )
    rule = Rule(RULE_TOP, [clause])
    rule.compute_quality(meta)
    assert rule.abstractness == 95.0
