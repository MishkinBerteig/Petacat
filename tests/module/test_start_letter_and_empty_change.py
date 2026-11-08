"""Metacat Mode follows fixes 0005 and 0006 of patched Metacat.

Real Slipnet, real Workspace; no database and no HTTP.

**0005, a group image with no start letter** (``Metacat/patches/fixes/0005-group-image-with-no-start-letter.patch``).
A group whose first object is a length-based group has no letter category, so its image is
made with the start letter ``#f`` (``groups.ss:81-82``, ``:90``).  ``new-start-letter`` then
sent ``get-related-node`` to it at ``images.ss:281`` (group branch) and ``images.ss:274``
(letter-image branch).  Patched Metacat now keeps a group image's none as none (the sub-images
have already been given the relation) and makes a letter image with none fail.  A group image
with a start letter is assigned its related node unconditionally, as ``images.ss:281`` does.

**0006, a change with only a literal descriptor** (``Metacat/patches/fixes/0006-literal-only-change-not-describable.patch``).
``make-change-template`` (``rules.ss:1060-1065``) empties the descriptor list of a literal
DirCtgy change, and ``possible-to-instantiate?`` (``rules.ss:445-458``) now refuses a template
with an empty list, so ``rule-scout`` fizzles.
"""

from __future__ import annotations

import os

import pytest

from server.engine.images import Image, ImageFailure, make_letter_image
from server.engine.metadata import MetadataProvider
from server.engine.rules import possible_to_instantiate
from server.engine.run_binding import constants
from server.engine.runner import EngineRunner

pytestmark = pytest.mark.numeric_matrix

SEED_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "seed_data")


@pytest.fixture(scope="module")
def ctx():
    runner = EngineRunner(MetadataProvider.from_standard_configuration(SEED_DIR))
    runner.init_mcat("abc", "abd", "xyz", seed=1)
    return runner.ctx


def _node(ctx, name):
    return ctx.slipnet.nodes[f"plato-{name}"]


def _group_image(ctx, start, letters):
    """A group image (letters ``letters``, relation successor) with start letter *start*."""
    return Image(
        slipnet=ctx.slipnet,
        start_letter=start,
        bond_facet=_node(ctx, "letter-category"),
        letter_relation=_node(ctx, "successor"),
        length_relation=_node(ctx, "identity"),
        direction=_node(ctx, "right"),
        sub_images=[make_letter_image(_node(ctx, c), ctx.slipnet) for c in letters],
    )


def test_a_letter_image_with_no_start_letter_fails(ctx):
    """images.ss:274: no start letter has no related letter, so the branch fails."""
    image = make_letter_image(None, ctx.slipnet)
    with pytest.raises(ImageFailure):
        image.new_start_letter(_node(ctx, "successor"))
    assert image.start_letter is None


@pytest.mark.parametrize("relation", ["successor", "predecessor", "identity"])
def test_a_group_image_with_no_start_letter_keeps_none(ctx, relation):
    """images.ss:281: none stays none; the sub-images have already been given the relation."""
    image = _group_image(ctx, None, "bc")
    image.new_start_letter(_node(ctx, relation))
    assert image.start_letter is None
    expected = {"successor": ["c", "d"], "predecessor": ["a", "b"], "identity": ["b", "c"]}[relation]
    assert [sub.start_letter.short_name for sub in image.sub_images] == expected


def test_a_group_image_with_a_start_letter_takes_its_related_node(ctx):
    image = _group_image(ctx, _node(ctx, "a"), "ab")
    image.new_start_letter(_node(ctx, "successor"))
    assert image.start_letter is _node(ctx, "b")


def test_a_start_letter_with_no_related_node_becomes_none(ctx):
    """images.ss:281 assigns unconditionally; Petacat used to keep the old letter."""
    image = _group_image(ctx, _node(ctx, "a"), "bc")
    image.new_start_letter(_node(ctx, "predecessor"))
    assert image.start_letter is None
    assert [sub.start_letter.short_name for sub in image.sub_images] == ["a", "b"]


def test_a_template_with_no_descriptor_to_pick_is_not_describable(ctx):
    """rules.ss:450 (fix 0006): an empty descriptor list makes ``rule-scout`` fizzle."""
    vocab = constants().vocab
    string = ctx.workspace.initial_string
    scope = vocab.rule_scope_subobjects
    dimension = ctx.slipnet.roles.dimension_bond_facet
    descriptor = _node(ctx, "letter-category")
    assert possible_to_instantiate([(vocab.clause_type_intrinsic, string, [(scope, dimension, [descriptor])])],
                                   ctx.slipnet)
    assert not possible_to_instantiate([(vocab.clause_type_intrinsic, string, [(scope, dimension, [])])],
                                       ctx.slipnet)
    # One empty change template among several is enough.
    assert not possible_to_instantiate(
        [(vocab.clause_type_intrinsic, string,
          [(scope, dimension, [descriptor]), (scope, dimension, [])])],
        ctx.slipnet)
