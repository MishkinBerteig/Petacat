"""Faithfulness fixes found by replaying Metacat runs beyond the lockstep corpus.

Each test pins one behaviour that differed from the Scheme and made a replay desynchronise
(or an answer description's themes differ); the traces that found them are in
``tests/lockstep/traces-desync/`` and are replayed by ``tests/lockstep/test_desync_fixes.py``.
These are the same faults as small, hand-built Workspace states, with the Scheme cited.
DISCREPANCIES5 G-Y1 ... G-Y5.
"""

from __future__ import annotations

import os
import types

import pytest

from server.engine.bridges import BRIDGE_VERTICAL, Bridge
from server.engine.concept_mappings import ConceptMapping
from server.engine.descriptions import Description
from server.engine.groups import Group
from server.engine.metadata import MetadataProvider
from server.engine.rules import (
    SCOPE_SELF,
    SCOPE_SUBOBJECTS,
    Rule,
    RuleChange,
    RuleClause,
    _find_matching_objects,
    rule_signature,
    rules_equal,
)
from server.engine.runner import EngineRunner

pytestmark = pytest.mark.numeric_matrix

SEED_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "seed_data")


@pytest.fixture(scope="module")
def meta():
    return MetadataProvider.from_standard_configuration(SEED_DIR)


def _engine(meta, initial="abc", modified="abd", target="xyz"):
    runner = EngineRunner(meta)
    runner.init_mcat(initial, modified, target, seed=42)
    return runner.ctx


# -- G-Y1  Workspace.get-equivalent-bridge (workspace.ss:266-301) ----------------------


def _group(ctx, string, category, direction):
    nodes = ctx.slipnet.nodes
    group = Group(
        string=string,
        group_category=nodes[category],
        bond_facet=nodes["plato-letter-category"],
        direction=nodes[direction],
        objects=list(string.letters),
        bonds=[],
    )
    return group


def _bridge(ctx, o1, o2):
    return Bridge(o1, o2, BRIDGE_VERTICAL, [])


def test_a_bridge_on_a_group_read_the_other_way_is_not_equivalent_to_the_built_one(meta):
    """``get-equivalent-group`` wants the same category, direction and length
    (``workspace-strings.ss:227-240``).  Same span is not enough: a bridge between
    ``[ijk]`` read as a successor group and ``[kji]``-style predecessor reading of the
    same letters is a different bridge, and a slippage event resting on the first is
    not "still present" once only the second stands (the ``ijll`` themes of lockstep
    ``aabc-aabd-ijkk`` episode 1, run 7)."""
    ctx = _engine(meta, "ijk", "ijl", "ijk")
    init, targ = ctx.workspace.initial_string, ctx.workspace.target_string
    succ_i = _group(ctx, init, "plato-succgrp", "plato-right")
    succ_t = _group(ctx, targ, "plato-succgrp", "plato-right")
    for g, s in ((succ_i, init), (succ_t, targ)):
        g.proposal_level = Group.BUILT
        s.add_group(g)
    built = _bridge(ctx, succ_i, succ_t)
    built.proposal_level = Bridge.BUILT
    ctx.workspace.add_bridge(built)
    succ_i.vertical_bridge = built
    succ_t.vertical_bridge = built

    # The same bridge, rebuilt over equivalent groups: present.
    twin_i = _group(ctx, init, "plato-succgrp", "plato-right")
    twin_t = _group(ctx, targ, "plato-succgrp", "plato-right")
    assert ctx.workspace.bridge_present(_bridge(ctx, twin_i, twin_t))

    # Groups over the same letters but read as predecessor groups, going left: not.
    pred_i = _group(ctx, init, "plato-predgrp", "plato-left")
    pred_t = _group(ctx, targ, "plato-predgrp", "plato-left")
    assert not ctx.workspace.bridge_present(_bridge(ctx, pred_i, pred_t))


# -- G-Y2  rule clauses differing only in self / subobjects (rules.ss:375-382) --------------


def _rule(ctx, referent):
    nodes = ctx.slipnet.nodes
    change = RuleChange(
        dimension=nodes["plato-letter-category"],
        to_descriptor=None,
        relation=nodes["plato-successor"],
        referent=referent,
    )
    clause = RuleClause(
        "intrinsic",
        object_description=(
            nodes["plato-group"],
            nodes["plato-string-position-category"],
            nodes["plato-whole"],
        ),
        changes=[change],
    )
    return Rule("top", [clause])


def test_changing_the_whole_group_and_changing_its_letters_are_different_rules(meta):
    """``(equal? (3rd rc1) (3rd rc2))`` compares ``(self ...)`` with ``(subobjects ...)``.
    ``abc -> bcd`` read as "the group becomes its successor" and as "each letter becomes
    its successor" are two rules; calling them one made ``rule-builder`` fizzle on the
    second and Petacat never posted the ``answer-finder`` Metacat did (lockstep
    ``abc-bcd-xyz`` seeds 1, 12 ...)."""
    ctx = _engine(meta)
    whole = _rule(ctx, SCOPE_SELF)
    letters = _rule(ctx, SCOPE_SUBOBJECTS)
    assert not rules_equal(whole, letters)
    assert rules_equal(whole, _rule(ctx, SCOPE_SELF))
    assert rule_signature(whole) != rule_signature(letters)
    # Signatures of ordinary ``self`` changes are unchanged, so stored answers still match.
    assert all(len(c) == 4 for c in rule_signature(whole)[0][2])


# -- G-Y3  a letter that is both ``single`` and ``rightmost`` (workspace-strings.ss:456-458) -----


def test_a_reference_object_matches_any_of_its_descriptions_of_that_type(meta):
    """``(filter-meth ... 'descriptor-present? descriptor)``: an object holding two
    string-position descriptors matches either.  ``a`` in the one-letter string "a" is
    ``single`` and, once a scout adds it, ``rightmost`` too; "change the rightmost
    letter" must find it (lockstep ``a-b-xyz`` seed 1, c=226)."""
    ctx = _engine(meta, "a", "b", "xyz")
    nodes = ctx.slipnet.nodes
    string = ctx.workspace.initial_string
    letter = string.letters[0]
    position = nodes["plato-string-position-category"]
    held = {d.descriptor.name for d in letter.descriptions if d.description_type is position}
    assert "plato-single" in held
    if "plato-rightmost" not in held:
        description = Description(letter, position, nodes["plato-rightmost"])
        description.proposal_level = Description.BUILT
        letter.descriptions.append(description)
    for name in ("plato-single", "plato-rightmost"):
        found = _find_matching_objects(
            (nodes["plato-letter"], position, nodes[name]), string, ctx.slipnet
        )
        assert found == [letter], name


# -- G-Y5  internally-coherent? tries both orders (bridges.ss:365-370) -------------------------


def _cm(label, d1, d2):
    return types.SimpleNamespace(
        label=label, descriptor1=d1, descriptor2=d2, description_type1=None
    )


def test_internal_coherence_tests_every_ordered_pair_of_mappings(meta):
    """``cross-product-ormap`` over the list against itself, skipping ``eq?`` pairs.
    ``related?`` follows outgoing links from its first argument, so the letter ``a``
    (linked to the property ``first``) supports ``first=>first`` one way and not the
    other; one pass over the unordered pairs found it only when the mappings happened
    to come in the right order."""
    ctx = _engine(meta)
    nodes = ctx.slipnet.nodes
    identity = nodes["plato-identity"]
    a, first = nodes["plato-a"], nodes["plato-alphabetic-first"]
    assert any(l.to_node is first for l in a.outgoing_links)
    assert not any(l.to_node is a for l in first.outgoing_links)

    for order in ([_cm(identity, first, first), _cm(identity, a, a)],
                  [_cm(identity, a, a), _cm(identity, first, first)]):
        stub = types.SimpleNamespace(
            get_relevant_distinguishing_concept_mappings=lambda order=order: order
        )
        assert Bridge._is_internally_coherent(stub) is True


# -- G-Y8  remove-duplicates keeps the last occurrence (utilities.ss:915-929) -----------------


def test_the_concept_pattern_of_a_theme_pattern_keeps_the_last_of_a_repeated_entry():
    """``get-associated-concept-pattern`` (``trace.ss:1503-1516``) is
    ``(remove-duplicates (flatmap ...))``: with two ``opposite`` themes, ``Opposite``
    stays where the second one put it, after the dimension of the second.  A justify
    clamp applies the pattern in this order, so the concept-activation events follow it
    (``rst-rsu-xyz-wyz`` seed 4: Metacat logs ObjectCtgy before Opposite)."""
    from server.engine.trace import get_associated_concept_pattern

    pattern = {
        "type": "vertical_bridge",
        "entries": [
            {"dimension": "plato-direction-category", "relation": "opposite", "activation": 100.0},
            {"dimension": "plato-object-category", "relation": "identity", "activation": 100.0},
            {"dimension": "plato-string-position-category", "relation": "opposite", "activation": 100.0},
        ],
    }
    nodes = [e["node"] for e in get_associated_concept_pattern(pattern)["entries"]]
    assert nodes == [
        "plato-direction-category",
        "plato-object-category",
        "plato-string-position-category",
        "plato-opposite",
    ]
