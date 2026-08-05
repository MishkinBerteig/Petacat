"""What a rule may name its object by, and whether that name finds anything.

Real Slipnet, real Workspace, real codelet interpreter; no database and no HTTP.

These cover the three defects that made Petacat's rules name objects the reference
cannot express, and then apply those rules to objects that were never there:

* ``get-descriptions-for-rule`` (``workspace-objects.ss:260-268``) — three kinds of
  description and no others;
* ``choose-description-for-rule`` (``workspace-objects.ss:270-275``) — a
  temperature-adjusted stochastic pick, not an argmax;
* ``object-description-possible?`` (``rules.ss:455-458``) — the gate that refuses a
  template naming an object with no legal description, instead of inventing one;
* ``distinguishing-descriptor?`` (``workspace-objects.ss:223-244``) — one predicate,
  and **any** sibling carrying the descriptor disqualifies it.

The consequences these guard against are answers, not internals. An ambiguous
object-description names several objects at once and the clauses collide, so no
rule is ever built and the run gives up; an unsatisfiable one names nothing, the
clause applies as a silent no-op, and the answer comes out as the target string
unchanged.
"""

from __future__ import annotations

import os

import pytest

from server.engine.metadata import MetadataProvider
from server.engine.rng import RNG
from server.engine.rules import (
    _choose_description_for_rule,
    _find_matching_objects,
    _object_description_possible,
    descriptions_for_rule,
    reference_object_to_object_description,
)
from server.engine.runner import EngineRunner
from server.engine.workspace_objects import distinguishing_descriptor

# Every test here reaches the numeric seam through ``init_mcat``'s first
# ``update-workspace-values``, so each runs once per backend. See tests/conftest.py.
pytestmark = pytest.mark.numeric_matrix

SEED_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "seed_data")

#: The description types a rule object-description may carry.  Anything else is a
#: name the reference cannot write.
LEGAL_TYPES = {
    "plato-string-position-category",
    "plato-alphabetic-position-category",
    "plato-letter-category",
}


@pytest.fixture(scope="module")
def meta():
    return MetadataProvider.from_seed_data(SEED_DIR)


def _engine(meta, initial, modified, target, seed=42):
    runner = EngineRunner(meta)
    runner.init_mcat(initial, modified, target, seed=seed)
    return runner


def _all_active(slipnet):
    for node in slipnet.nodes.values():
        node.activation = 100.0


def _letters(string):
    return list(string.letters)


# --- distinguishing-descriptor? --------------------------------------------


def test_a_descriptor_a_sibling_also_carries_does_not_distinguish(meta):
    """``workspace-objects.ss:223-244`` — ``(not (member? descriptor other-descriptors))``.

    In ``eqe`` the leftmost letter is an ``e`` and so is the rightmost, so ``e``
    picks out neither of them.  Reading this as "not *all* siblings carry it" —
    which two of the three call sites did — makes ``e`` distinguishing because the
    middle ``q`` differs, and that is what opened the bridge scout's gate to
    crossing bridges.
    """
    ctx = _engine(meta, "eqe", "qeq", "abbba").ctx
    node = ctx.slipnet.nodes
    left, middle, right = _letters(ctx.workspace.initial_string)

    assert distinguishing_descriptor(left, node["plato-e"]) is False
    assert distinguishing_descriptor(right, node["plato-e"]) is False
    # q is carried by no other letter of eqe, so it does distinguish.
    assert distinguishing_descriptor(middle, node["plato-q"]) is True


def test_one_predicate_answers_for_descriptions_and_concept_mappings(meta):
    """The three call sites agree because there is only one predicate.

    ``Description.is_distinguishing`` and
    ``ConceptMapping._descriptor_is_distinguishing`` were independently written
    copies of ``WorkspaceObject._is_distinguishing_descriptor``, and both had the
    quantifier the other way round.
    """
    from server.engine.concept_mappings import ConceptMapping

    ctx = _engine(meta, "eqe", "qeq", "abbba").ctx
    node = ctx.slipnet.nodes
    left = _letters(ctx.workspace.initial_string)[0]
    letcat = node["plato-letter-category"]

    description = next(
        d for d in left.descriptions if d.description_type is letcat
    )
    assert description.descriptor is node["plato-e"]

    verdict = distinguishing_descriptor(left, node["plato-e"])
    assert description.is_distinguishing() is verdict
    assert left._is_distinguishing_descriptor(node["plato-e"]) is verdict
    assert ConceptMapping._descriptor_is_distinguishing(node["plato-e"], left) is verdict


# --- get-descriptions-for-rule ---------------------------------------------


def test_a_group_may_not_be_named_by_its_group_category(meta):
    """``workspace-objects.ss:260-268`` admits three kinds of description.

    Group-Category is not one of them, and it is the one that did the damage:
    ``(group GroupCtgy samegrp)`` names *every* same-group of a string at once.
    """
    ctx = _engine(meta, "abc", "cba", "mrrjjj").ctx
    _all_active(ctx.slipnet)

    for string in (ctx.workspace.initial_string, ctx.workspace.target_string):
        for obj in string.objects:
            for d in descriptions_for_rule(obj):
                name = d.description_type.name
                assert name in LEGAL_TYPES, (
                    f"{name} is not a description a rule may name an object by"
                )


def test_letter_category_names_a_letter_but_not_a_successor_group(meta):
    """The Letter-Category clause of ``get-descriptions-for-rule`` is conditional.

    A letter, or a group whose category is same-group, may be named by its
    letter-category. A successor or predecessor group may not — it has no single
    letter-category to be named by.
    """
    ctx = _engine(meta, "abc", "cba", "mrrjjj").ctx
    _all_active(ctx.slipnet)
    node = ctx.slipnet.nodes
    from server.engine.groups import Group

    string = ctx.workspace.initial_string
    letters = _letters(string)
    letcat = node["plato-letter-category"]

    a = letters[0]
    assert any(d.description_type is letcat for d in descriptions_for_rule(a))

    succ_group = Group(
        string=string,
        group_category=node["plato-succgrp"],
        bond_facet=letcat,
        direction=node["plato-right"],
        objects=list(letters),
        bonds=[],
    )
    succ_group.proposal_level = succ_group.BUILT
    from server.engine.descriptions import Description

    succ_group.add_description(Description(succ_group, letcat, node["plato-a"]))
    string.add_group(succ_group)

    assert not any(
        d.description_type is letcat for d in descriptions_for_rule(succ_group)
    ), "a successor group must not be named by a letter-category"


def test_a_same_group_may_be_named_by_its_letter_category(meta):
    """The positive half of the same conditional.

    The category node is ``plato-samegrp``; testing against a name that does not
    exist in the Slipnet silently *excludes* every same-group instead of admitting
    it, which is a second way to get the eligible set wrong. ``mrrjjj`` is read as
    three same-groups, so it is the case that matters.
    """
    runner = _engine(meta, "abc", "abd", "mrrjjj", seed=1)
    runner.run_mcat(max_steps=4000)
    node = runner.ctx.slipnet.nodes
    letcat = node["plato-letter-category"]

    same_groups = [
        g
        for g in runner.ctx.workspace.target_string.groups
        if g.group_category is node["plato-samegrp"]
    ]
    assert same_groups, "precondition: mrrjjj was read as same-groups"
    assert any(
        any(d.description_type is letcat for d in descriptions_for_rule(g))
        for g in same_groups
    ), "a same-group may be named by its letter-category"


# --- object-description-possible? ------------------------------------------


def test_an_object_with_no_legal_description_cannot_be_named(meta):
    """``rules.ss:455-458`` gates on the *rule-eligible* descriptions.

    Gating on "has any description at all" let a template through and then invented
    a name for it downstream, which is how ``(letter ObjectCtgy letter)`` reached
    built rules.
    """
    ctx = _engine(meta, "abc", "cba", "mrrjjj").ctx
    node = ctx.slipnet.nodes
    letter = _letters(ctx.workspace.initial_string)[0]

    # Object-category alone: a description, but not one a rule may use.
    letter.descriptions = [
        d for d in letter.descriptions
        if d.description_type is node["plato-object-category"]
    ]
    assert letter.descriptions, "precondition: the object still has a description"

    assert descriptions_for_rule(letter) == []
    assert _object_description_possible(letter) is False
    assert reference_object_to_object_description(letter, ctx.slipnet)[1] is None


# --- choose-description-for-rule -------------------------------------------


def test_the_object_description_is_drawn_stochastically_not_by_argmax(meta):
    """``workspace-objects.ss:270-275`` is a ``stochastic-pick``.

    Taking ``max`` on conceptual depth removed a source of variation the reference
    has and pinned every rule on one descriptor. With two eligible descriptions the
    draw must be able to reach both.
    """
    ctx = _engine(meta, "abc", "cba", "mrrjjj").ctx
    _all_active(ctx.slipnet)
    letter = _letters(ctx.workspace.initial_string)[0]

    eligible = descriptions_for_rule(letter)
    if len(eligible) < 2:
        pytest.skip("this object offers only one eligible description")

    seen = set()
    for seed in range(60):
        chosen = _choose_description_for_rule(
            letter, RNG(seed), temperature=100.0, meta=meta
        )
        seen.add(id(chosen))
    assert len(seen) > 1, "the choice never varied — it is still an argmax"


# --- the consequence: a clause that names nothing ---------------------------


def test_no_rule_names_the_target_by_a_description_the_target_lacks(meta):
    """The failure this whole group exists to prevent, at the level of an answer.

    ``abc -> cba; mrrjjj?`` reaches ``jjjrrm`` by reversing the direction of the
    whole thing. Petacat named the object ``(group GroupCtgy succgrp)``; ``mrrjjj``
    has no successor group, the clause resolved to nothing, ``apply_rule`` returned
    an empty transform list without complaint, and the answer was the target string
    unchanged — 66% of runs against the reference's 8.7%.
    """
    runner = _engine(meta, "abc", "cba", "mrrjjj", seed=3)
    runner.run_mcat(max_steps=20000)
    ws = runner.ctx.workspace

    for rule in ws.top_rules + ws.bottom_rules:
        for clause in rule.clauses:
            for od in clause.object_descriptions:
                if not od or od[0] == "string" or od[1] is None:
                    continue
                assert od[1].name in LEGAL_TYPES, (
                    f"rule clause names its object by {od[1].name}"
                )

    for rule in ws.bottom_rules:
        for clause in rule.clauses:
            if clause.is_verbatim:
                continue
            for od in clause.object_descriptions:
                if not od or od[0] == "string" or od[1] is None:
                    continue
                matched = _find_matching_objects(od, ws.target_string, runner.ctx.slipnet)
                assert matched, (
                    f"a built bottom rule names {od[1].name}:{od[2].name}, which "
                    "matches nothing in the target — it would apply as a no-op"
                )
