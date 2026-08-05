"""Every object a rule names must own an image, singleton groups included.

Real Slipnet, real Workspace; no database and no HTTP.

In the reference an object owns an image from the moment it is constructed
(``groups.ss:84``), so "the middle group" always has one to transform. Petacat
builds the image tree lazily from the string image, partitioning the string by
position and taking the widest object starting at each one — and a **singleton
group** spans exactly the position of the letter it encloses, so the two tie.
``max`` is first-wins and ``string.objects`` lists letters before groups, so the
letter used to win and the group's image stayed ``None``.

``apply_rule`` then skipped that object's transforms *in silence*, which does not
decline to apply the rule: it applies a different one and reports the result as an
answer. On ``eeqee -> qeeq`` the three-clause rule over the leftmost, middle and
rightmost groups generated ``qqq``, ``currently_works`` passed 2 times in 2,736,
no rule was ever built, and 71% of runs gave up.
"""

from __future__ import annotations

import os

import pytest

from server.engine.descriptions import Description
from server.engine.groups import Group
from server.engine.images import ImageFailure
from server.engine.metadata import MetadataProvider
from server.engine.rules import (
    CLAUSE_INTRINSIC,
    Rule,
    RuleChange,
    RuleClause,
    _generate_image_letters,
    apply_rule,
)
from server.engine.runner import EngineRunner

# Every test here reaches the numeric seam through ``init_mcat``'s first
# ``update-workspace-values``, so each runs once per backend. See tests/conftest.py.
pytestmark = pytest.mark.numeric_matrix

SEED_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "seed_data")


@pytest.fixture(scope="module")
def meta():
    return MetadataProvider.from_seed_data(SEED_DIR)


def _engine(meta, initial, modified, target, seed=42):
    runner = EngineRunner(meta)
    runner.init_mcat(initial, modified, target, seed=seed)
    return runner


def _same_group(ctx, string, letters, *, length_node=None):
    """A built same-group over *letters*, described the way the engine describes one."""
    node = ctx.slipnet.nodes
    group = Group(
        string=string,
        group_category=node["plato-samegrp"],
        bond_facet=node["plato-letter-category"],
        direction=None,
        objects=list(letters),
        bonds=[],
    )
    group.proposal_level = group.BUILT
    group.add_description(
        Description(group, node["plato-object-category"], node["plato-group"])
    )
    group.add_description(
        Description(group, node["plato-group-category"], node["plato-samegrp"])
    )
    group.add_description(
        Description(
            group,
            node["plato-letter-category"],
            letters[0].letter_category,
        )
    )
    if length_node is not None:
        group.add_description(Description(group, node["plato-length"], length_node))
    string.add_group(group)
    for letter in letters:
        letter.enclosing_group = group
    return group


def _eeqee_groups(ctx):
    """``eeqee`` read as ``[ee] [q] [ee]`` — the middle one a *singleton* group."""
    node = ctx.slipnet.nodes
    string = ctx.workspace.initial_string
    letters = list(string.letters)
    left = _same_group(ctx, string, letters[0:2], length_node=node["plato-two"])
    middle = _same_group(ctx, string, letters[2:3], length_node=node["plato-one"])
    right = _same_group(ctx, string, letters[3:5], length_node=node["plato-two"])
    _position_descriptions(ctx, [left, middle, right])
    return left, middle, right


def _position_descriptions(ctx, groups):
    node = ctx.slipnet.nodes
    strpos = node["plato-string-position-category"]
    for group, where in zip(groups, ("plato-leftmost", "plato-middle", "plato-rightmost")):
        group.add_description(Description(group, strpos, node[where]))


def _clause(ctx, group, changes):
    """An intrinsic clause naming *group* by its string-position."""
    node = ctx.slipnet.nodes
    strpos = node["plato-string-position-category"]
    descriptor = next(
        d.descriptor for d in group.descriptions if d.description_type is strpos
    )
    return RuleClause(
        clause_type=CLAUSE_INTRINSIC,
        object_description=(node["plato-group"], strpos, descriptor),
        changes=changes,
    )


def test_a_singleton_group_is_a_constituent_of_the_string_image(meta):
    """The tie between a singleton group and its letter goes to the group.

    ``get-top-level-objects`` (``workspace-strings.ss:411-417``) selects on having
    no enclosing group, and the letter inside a singleton group has one.
    """
    ctx = _engine(meta, "eeqee", "qeeq", "xxixx").ctx
    _left, middle, _right = _eeqee_groups(ctx)

    from server.engine.images import make_string_image

    image = make_string_image(
        ctx.workspace.initial_string, ctx.slipnet.nodes["plato-right"], ctx.slipnet
    )
    image.get_sub_images()

    assert middle.image is not None, (
        "the singleton group around q never received an image, so a rule naming "
        "the middle group would have its transforms silently skipped"
    )
    assert len(image.get_sub_images()) == 3, "the string image should be [ee][q][ee]"


def test_the_reference_rule_for_eeqee_generates_qeeq(meta):
    """MetaCat's own rule for this problem, applied here.

    "Change letter-category of leftmost group to `q', decrease its length by one;
    change letter-category of middle group to `e', increase its length by one;
    change letter-category of rightmost group to `q', decrease its length by one."
    That is the rule MetaCat builds in roughly half its runs on ``eeqee -> qeeq``.
    It generated ``qqq`` here, because the middle group's two changes went nowhere.
    """
    ctx = _engine(meta, "eeqee", "qeeq", "xxixx").ctx
    node = ctx.slipnet.nodes
    left, middle, right = _eeqee_groups(ctx)

    def letcat_and_length(letter_name, length_relation):
        return [
            RuleChange(
                dimension=node["plato-letter-category"],
                to_descriptor=node[letter_name],
                referent="self",
            ),
            RuleChange(
                dimension=node["plato-length"],
                relation=node[length_relation],
                referent="self",
            ),
        ]

    rule = Rule(
        rule_type="top",
        clauses=[
            _clause(ctx, left, letcat_and_length("plato-q", "plato-predecessor")),
            _clause(ctx, middle, letcat_and_length("plato-e", "plato-successor")),
            _clause(ctx, right, letcat_and_length("plato-q", "plato-predecessor")),
        ],
        workspace=ctx.workspace,
    )

    assert apply_rule(rule, ctx.workspace.initial_string, ctx.slipnet) is not None
    generated = "".join(
        n.short_name for n in _generate_image_letters(
            ctx.workspace.initial_string, ctx.slipnet
        )
    )
    assert generated == "qeeq", f"eeqee generated {generated!r}, expected 'qeeq'"


def test_a_named_object_with_no_image_fails_rather_than_being_skipped(meta):
    """A missing image is a structural inconsistency, not a licence to answer.

    The reference has no such case — every object owns an image — so it has no
    branch for it either. Raising routes the miss into the snag machinery instead
    of quietly producing a different answer.
    """
    ctx = _engine(meta, "eeqee", "qeeq", "xxixx").ctx
    node = ctx.slipnet.nodes
    _left, middle, _right = _eeqee_groups(ctx)

    rule = Rule(
        rule_type="top",
        clauses=[
            _clause(
                ctx,
                middle,
                [
                    RuleChange(
                        dimension=node["plato-letter-category"],
                        to_descriptor=node["plato-e"],
                        referent="self",
                    )
                ],
            )
        ],
        workspace=ctx.workspace,
    )

    failures: list[ImageFailure] = []
    # Force the miss the tie-break used to cause, without reintroducing it.
    from server.engine import rules as rules_module

    original = rules_module._get_object_image
    rules_module._get_object_image = lambda obj, slipnet: (
        None if obj is middle else original(obj, slipnet)
    )
    try:
        result = apply_rule(
            rule, ctx.workspace.initial_string, ctx.slipnet, failures.append
        )
    finally:
        rules_module._get_object_image = original

    assert result is None, "application must fail, not skip the object"
    assert failures and failures[0].objects == [middle]
