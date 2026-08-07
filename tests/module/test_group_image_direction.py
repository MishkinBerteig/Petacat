"""A group's image is built in the group's own direction.

Real Slipnet, real Workspace; no database and no HTTP.

``new-group`` (``groups.ss:70-98``) seeds a group's image off ``ordered-objects``
— the group's objects reversed when it goes left — and hands the image the
group's own direction. Petacat rebuilds the tree lazily in
``StringImage._make_image_for``, and it used to build every group left-to-right
with ``plato-right``.

That is invisible in an untouched image, which is what makes it worth a test:
``generate`` reverses a left-going image's sub-images again
(``images.ss:227-231``), so the two reversals cancel and the letters come out in
the same order either way. It shows up only once a rule transforms the image.
``new_start_letter`` with a literal letter enumerates from the group's *first
object in direction order* using its letter relation, so on a left-going
predecessor group the reference walks leftward through predecessors and Petacat
walked rightward through successors — a different string, or, where the reference
runs off the end of the alphabet and snags, no change at all. On
``eqe → qeq ; abbba`` that answered ``abbbb``, a state absent from MetaCat's
51,000-run reference set.

The two halves have to be tested together. Flipping the direction *without*
reversing the sub-image list is the failure the previous implementation's comment
recorded — an untouched ``abc`` coming out ``acb`` — so
``test_an_untouched_image_generates_left_to_right`` guards that half and the two
enumeration tests guard the other.
"""

from __future__ import annotations

import os

import pytest

from server.engine.descriptions import Description
from server.engine.groups import Group
from server.engine.images import ImageFailure, make_string_image
from server.engine.metadata import MetadataProvider
from server.engine.runner import EngineRunner

# ``init_mcat``'s first ``update-workspace-values`` crosses the numeric seam, so
# each of these runs once per backend. See tests/conftest.py.
pytestmark = pytest.mark.numeric_matrix

SEED_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "seed_data")


@pytest.fixture(scope="module")
def meta():
    return MetadataProvider.from_seed_data(SEED_DIR)


def _ctx(meta, initial="ab", modified="c", target="ab"):
    runner = EngineRunner(meta)
    runner.init_mcat(initial, modified, target, seed=42)
    return runner.ctx


def _directed_group(ctx, category, direction):
    """``ab`` read as one group of its two letters, going *direction*.

    With ``plato-left`` and ``plato-predgrp`` this is the reading "b, then its
    predecessor a" — the shape ``abbba`` takes when the run that answered
    ``abbbb`` read it.
    """
    node = ctx.slipnet.nodes
    string = ctx.workspace.initial_string
    letters = list(string.letters)
    group = Group(
        string=string,
        group_category=node[category],
        bond_facet=node["plato-letter-category"],
        direction=node[direction] if direction is not None else None,
        objects=letters,
        bonds=[],
    )
    group.proposal_level = group.BUILT
    group.add_description(
        Description(group, node["plato-object-category"], node["plato-group"])
    )
    group.add_description(
        Description(group, node["plato-group-category"], node[category])
    )
    group.add_description(
        Description(
            group,
            node["plato-letter-category"],
            group._get_initial_letter_category(),
        )
    )
    string.add_group(group)
    for letter in letters:
        letter.enclosing_group = group
    return group


def _build_images(ctx):
    string = ctx.workspace.initial_string
    for obj in string.objects:
        obj.image = None
    image = make_string_image(string, ctx.slipnet.nodes["plato-right"], ctx.slipnet)
    string.image = image
    image.get_sub_images()
    return image


def _generated(ctx):
    from server.engine.rules import _generate_image_letters

    return "".join(
        n.short_name
        for n in _generate_image_letters(ctx.workspace.initial_string, ctx.slipnet)
    )


def test_an_untouched_image_generates_left_to_right(meta):
    """Both reversals or neither: an untouched group prints as it reads.

    This is the regression the previous implementation avoided by dropping the
    direction altogether. ``abc`` came out ``acb`` when the image carried
    ``plato-left`` while its sub-images were still in string order, and every rule
    then looked broken to ``currently_works``.
    """
    for category, direction in (("plato-predgrp", "plato-left"),
                                ("plato-succgrp", "plato-right"),
                                ("plato-samegrp", None)):
        ctx = _ctx(meta)
        group = _directed_group(ctx, category, direction)
        _build_images(ctx)

        assert group.image is not None
        assert _generated(ctx) == "ab", (
            f"an untouched {category} going {direction} generated "
            f"{_generated(ctx)!r}, not the string it was built over"
        )


def test_a_left_going_image_enumerates_from_its_own_first_object(meta):
    """``new_start_letter`` walks the group in direction order.

    ``images.ss:282-286`` enumerates ``n`` letters from the new start letter
    through the image's letter relation and hands them to the sub-images *in the
    image's own order*. For the left-going ``[b→a]`` reading of ``ab``, start
    letter ``c`` gives ``c`` then its predecessor ``b`` — to the rightmost letter
    and then the leftmost — so the string reads ``bc``. Built left-to-right the
    same image has start letter ``a`` and relation successor, and the same request
    produced ``cd``.
    """
    ctx = _ctx(meta)
    group = _directed_group(ctx, "plato-predgrp", "plato-left")
    _build_images(ctx)

    node = ctx.slipnet.nodes
    assert group.image.direction is node["plato-left"]
    assert group.image.start_letter is node["plato-b"], (
        "the image's start letter is the LettCtgy of its first object in "
        "direction order (groups.ss:76-77), which here is the rightmost letter"
    )
    assert group.image.letter_relation is node["plato-predecessor"]

    group.image.new_start_letter(node["plato-c"])
    assert _generated(ctx) == "bc", (
        f"enumerating from c through predecessor gave {_generated(ctx)!r}"
    )


def test_enumerating_off_the_end_of_the_alphabet_fails(meta):
    """The reference snags here; Petacat used to change nothing and answer.

    ``enumerate-letter`` (``images.ss:380-395``) calls its failure continuation
    when a step has no related node, and ``a`` has no predecessor. Running the
    reference headless over ``eqe → qeq ; abbba`` reaches exactly this — a
    left-going two-object image, relation predecessor, asked for start letter
    ``a`` — and fails, which routes the rule application into the snag machinery.

    Built left-to-right the same image had relation *successor*, so the request
    enumerated ``a`` then ``b``, handed each sub-image the letter it already had,
    and silently changed nothing.
    """
    ctx = _ctx(meta)
    group = _directed_group(ctx, "plato-predgrp", "plato-left")
    _build_images(ctx)
    node = ctx.slipnet.nodes

    with pytest.raises(ImageFailure):
        group.image.new_start_letter(node["plato-a"])

    # The mirror: the same request on a right-going successor group is legal, so
    # the failure above is the alphabet's edge and not left-going images as such.
    ctx = _ctx(meta)
    group = _directed_group(ctx, "plato-succgrp", "plato-right")
    _build_images(ctx)
    group.image.new_start_letter(ctx.slipnet.nodes["plato-a"])
    assert _generated(ctx) == "ab"


def test_a_left_going_group_grows_at_the_end_it_reads_towards(meta):
    """``extend`` appends past the *last* sub-image, which direction decides.

    ``images.ss:325-343`` copies the last sub-image, moves it on by the group's
    letter relation, and appends. For the left-going ``[c→b]`` reading of ``bc``
    the last sub-image is ``b`` and the relation is predecessor, so the group
    grows to ``abc`` — leftward, which is where a group reading right-to-left
    continues. Built left-to-right the same image had ``c`` last and successor for
    a relation, and grew to ``bcd``: the same rule, the opposite end of the
    string.
    """
    ctx = _ctx(meta, "bc", "d", "bc")
    group = _directed_group(ctx, "plato-predgrp", "plato-left")
    _build_images(ctx)
    node = ctx.slipnet.nodes
    assert group.image.letter_relation is node["plato-predecessor"]

    group.image.new_length(node["plato-successor"])
    assert _generated(ctx) == "abc", (
        f"a left-going group extended by one gave {_generated(ctx)!r}"
    )


def test_the_length_relation_is_read_in_direction_order_too(meta):
    """Not only the letters: ``groups.ss:93-95`` relates the lengths the same way.

    ``abb`` read leftward as ``[bb]`` then ``[a]`` has lengths two, one — a
    *predecessor* relation. Read left-to-right it is one, two, a successor, and
    ``extend`` would then lengthen the copy it appends instead of shortening it.
    The letter relation is pinned by the tests above; this is the same one-line
    ordering on the other dimension, and it has its own consequences.
    """
    from server.engine.groups import Group

    ctx = _ctx(meta, "abb", "c", "abb")
    node = ctx.slipnet.nodes
    string = ctx.workspace.initial_string
    letters = list(string.letters)

    inner = Group(
        string=string,
        group_category=node["plato-samegrp"],
        bond_facet=node["plato-letter-category"],
        direction=None,
        objects=letters[1:3],
        bonds=[],
    )
    inner.proposal_level = inner.BUILT
    inner.add_description(
        Description(inner, node["plato-letter-category"], node["plato-b"])
    )
    string.add_group(inner)
    for letter in letters[1:3]:
        letter.enclosing_group = inner

    outer = Group(
        string=string,
        group_category=node["plato-predgrp"],
        bond_facet=node["plato-length"],
        direction=node["plato-left"],
        objects=[letters[0], inner],
        bonds=[],
    )
    outer.proposal_level = outer.BUILT
    string.add_group(outer)
    letters[0].enclosing_group = outer
    inner.enclosing_group = outer

    _build_images(ctx)

    assert outer.image is not None
    assert outer.image.length_relation is node["plato-predecessor"], (
        "lengths two then one, in the order the group reads them"
    )
    assert _generated(ctx) == "abb", "and it still generates the string it was built over"


def test_a_group_instantiated_from_a_left_going_image_goes_left(meta):
    """The answer string inherits the reading, direction included.

    ``instantiate-as-group`` (``images.ss:180-206``) orders the new group's
    objects by the image's direction and passes that direction on, so an answer
    built from a left-going image is *drawn* as a left-going group. With every
    image built ``plato-right`` the answer's own structure said something the
    target's did not.
    """
    from server.engine.workspace import WorkspaceString

    ctx = _ctx(meta)
    group = _directed_group(ctx, "plato-predgrp", "plato-left")
    _build_images(ctx)

    answer = WorkspaceString("ab", ctx.slipnet, string_type="answer")
    letters = list(answer.letters)
    position = 0

    def bind(leaf):
        nonlocal position
        leaf.instantiated_object = letters[position]
        position += 1

    group.image.leaf_walk(bind)
    assert position == len(letters)
    group.image.postorder_interior_walk(lambda node: node.instantiate_as_group(answer))

    built = group.image.instantiated_object
    assert built is not None
    assert built.direction is ctx.slipnet.nodes["plato-left"], (
        "a group instantiated from a left-going image must go left"
    )
    # ``images.ss:182-186`` reverses the sub-images *back* here, and names the
    # result's ends ``left-object`` and ``right-object`` — so a group's members
    # are stored left-to-right whatever its direction, and only the image holds
    # them in direction order.
    assert [o.left_string_pos for o in built.objects] == [0, 1]
