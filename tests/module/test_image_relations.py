"""The relations a group's image is built with, and what happens when they are wrong.

Real Slipnet, real Workspace, real codelet interpreter; no database and no HTTP.

A group's image carries a *letter relation* and a *length relation*
(``groups.ss:84-96``).  Those are what ``extend`` hands to ``new-start-letter``
when a rule lengthens a group (``images.ss:496``, ``images.ss:607``), and
``new-start-letter``'s declared domain is ``{pred succ iden} U {a … z}``
(``images.ss:164``).  ``plato-sameness`` is not in it: hand it over and the
image's ``start_letter`` becomes the relation node itself, which then generates
as its own short name.  The observable symptom is an answer string with a
relation's name embedded in it — ``kksamejjiisame`` instead of ``kkjjii``.

The two places the reference avoids that are both easy to miss, so both are
pinned here.
"""

from __future__ import annotations

import os

import pytest

from server.engine.metadata import MetadataProvider
from server.engine.rules import _generate_image_letters
from server.engine.runner import EngineRunner

pytestmark = pytest.mark.numeric_matrix

SEED_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "seed_data")

#: Every node that can legitimately appear in a generated letter list.
LETTERS = {f"plato-{c}" for c in "abcdefghijklmnopqrstuvwxyz"}


@pytest.fixture(scope="module")
def meta() -> MetadataProvider:
    return MetadataProvider.from_seed_data(SEED_DIR)


def _ctx(meta: MetadataProvider, initial: str, modified: str, target: str, seed: int):
    runner = EngineRunner(meta)
    runner.init_mcat(initial, modified, target, seed=seed)
    return runner


def _same_group(ctx, string, letters):
    """Build a sameness group over *letters* of *string* and return it."""
    from server.engine.bonds import Bond
    from server.engine.groups import Group

    node = ctx.slipnet.nodes.get
    sameness, samegrp = node("plato-sameness"), node("plato-samegrp")
    facet = node("plato-letter-category")
    bonds = [
        Bond(
            letters[i], letters[i + 1], sameness, facet,
            letters[i].letter_category, letters[i + 1].letter_category,
        )
        for i in range(len(letters) - 1)
    ]
    for b in bonds:
        b.proposal_level = b.BUILT
        string.add_bond(b)
    group = Group(string, samegrp, facet, None, letters, bonds)
    group.proposal_level = group.BUILT
    string.groups.append(group)
    for letter in letters:
        letter.enclosing_group = group
    return group


def test_a_sameness_groups_letter_relation_is_identity_not_sameness(meta):
    """``groups.ss:88-89`` relates the *constituents*, not the bonds.

    ``get-label`` answers ``plato-identity`` for a node against itself
    (``slipnet.ss:289-290``), so a group of two ``k``s relates its letters by
    Identity even though its bonds are categorised Sameness.  Reading the
    relation off ``group_bonds[0].bond_category`` instead gives Sameness, which
    is outside ``new-start-letter``'s domain.
    """
    runner = _ctx(meta, "abc", "aabbcc", "kkjjii", seed=1)
    ctx = runner.ctx
    target = ctx.workspace.target_string
    group = _same_group(ctx, target, target.letters[:2])

    from server.engine.images import _group_image_relations

    letter_relation, length_relation = _group_image_relations(
        group, list(group.objects), ctx.slipnet
    )
    assert letter_relation is ctx.slipnet.nodes.get("plato-identity")
    assert length_relation is ctx.slipnet.nodes.get("plato-identity")


def test_a_singleton_sameness_group_maps_its_bond_category_to_identity(meta):
    """``groups.ss:89-91``: with one constituent there is nothing to relate, so
    the reference falls back to the bond category — mapping Sameness to
    Identity on the way, for the same domain reason."""
    runner = _ctx(meta, "abc", "aabbcc", "kkjjii", seed=1)
    ctx = runner.ctx
    target = ctx.workspace.target_string
    group = _same_group(ctx, target, target.letters[:1])

    from server.engine.images import _group_image_relations

    letter_relation, length_relation = _group_image_relations(
        group, list(group.objects), ctx.slipnet
    )
    assert letter_relation is ctx.slipnet.nodes.get("plato-identity")
    assert length_relation is ctx.slipnet.nodes.get("plato-identity")


def test_a_singleton_successor_group_keeps_its_bond_category(meta):
    """The fallback is a *mapping*, not a blanket override: a successor group's
    relation stays ``plato-successor``, which is in the domain."""
    runner = _ctx(meta, "abc", "abd", "xyz", seed=1)
    ctx = runner.ctx
    from server.engine.groups import Group

    node = ctx.slipnet.nodes.get
    target = ctx.workspace.target_string
    group = Group(
        target, node("plato-succgrp"), node("plato-letter-category"),
        node("plato-right"), target.letters[:1], [],
    )

    from server.engine.images import _group_image_relations

    letter_relation, _ = _group_image_relations(group, list(group.objects), ctx.slipnet)
    assert letter_relation is ctx.slipnet.nodes.get("plato-successor")


#: Seeds that reach an answer on this problem within the budget, on both
#: backends. ``abc->aabbcc; kkjjii`` is the one problem where *not* answering is
#: ordinary rather than a defect — MetaCat itself caps 10.96% of its 19,000 runs
#: here and 24.9% of them pass 20,000 codelets — so a seed is chosen for
#: answering rather than assumed to. Seeds 11 and 23 were in this list and cap;
#: they contributed nothing but a skip.
ANSWERING_SEEDS = (1, 5, 7, 17, 29)


def test_a_generated_answer_is_made_only_of_letters(meta):
    """The end-to-end guard: whatever a run answers, every generated node is a
    platonic letter.

    ``abc->aabbcc; kkjjii`` is the problem that exposed this — it groups, and
    its rule lengthens groups, so it reaches ``extend`` with a group's letter
    relation in hand.

    One test over the seeds rather than one test per seed, because a seed that
    stops answering must not be able to take its coverage away quietly. Skipping
    per seed meant that if every seed stopped answering — which on *this* problem
    a change to the cap or to grouping could plausibly do — the whole guard would
    report green while checking nothing. A run that does not answer is still
    tolerated; a set of runs where none does is a failure.
    """
    answered = []
    for seed in ANSWERING_SEEDS:
        runner = _ctx(meta, "abc", "aabbcc", "kkjjii", seed=seed)
        runner.run_mcat(max_steps=20000)
        ctx = runner.ctx
        answer = ctx.workspace.answer_string
        if answer is None:
            continue
        answered.append(seed)

        generated = _generate_image_letters(ctx.workspace.target_string, ctx.slipnet)
        offenders = [n.name for n in generated if n.name not in LETTERS]
        assert not offenders, f"seed {seed}: non-letter nodes generated: {offenders}"
        assert answer.text.isalpha() and answer.text.islower(), (
            f"seed {seed}: {answer.text!r}"
        )

    assert answered, (
        f"none of {ANSWERING_SEEDS} reached an answer, so this guard checked "
        f"nothing — re-pick the seeds rather than leaving it silent"
    )
