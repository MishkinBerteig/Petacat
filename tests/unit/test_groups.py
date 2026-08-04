"""Unit tests for engine.groups.Group.

Group is both a WorkspaceObject and a WorkspaceStructure. These tests isolate
its own logic — length, membership, spanning, strength, flipping, and
constituent queries — using small positional fakes for the member objects and
the string. Slipnet nodes come from the shared fakes. The internal-strength
cases use precomputed expected values (the 0.98 self-weighting exponent makes
the arithmetic non-round) so the tests pin the formula rather than restate it.
No randomness is involved.
"""

from server.engine.groups import Group

from tests.unit._fakes import FakeNode, FakeString


class _PosObj:
    """A minimal positional member object."""

    def __init__(self, left, right):
        self.left_string_pos = left
        self.right_string_pos = right
        self.enclosing_group = None
        self.horizontal_bridge = None
        self.vertical_bridge = None
        self.descriptions = []


def _category(name="plato-succgrp", *, bond_category_name="plato-successor",
              intrinsic_link_length=60, fully_active=False):
    """A group category wired to its bond category, as ``new-group`` reads it.

    ``groups.ss:79`` derives the bond category from the *group* category, and the
    bond category's ``get-degree-of-assoc`` (slipnet.ss:90-91) is what the
    internal-strength formula multiplies.  succ/pred carry an intrinsic link
    length of 60 (degree 40, or 76 once the node is fully active); sameness
    carries 0 (degree 100).
    """
    return FakeNode(
        name,
        related={
            "plato-bond-category": FakeNode(
                bond_category_name,
                intrinsic_link_length=intrinsic_link_length,
                fully_active=fully_active,
            )
        },
    )


def _group(objects, *, bonds=None, facet=None, direction=None, string=None,
           category=None):
    return Group(
        string=string,
        group_category=category or _category(),
        bond_facet=facet or FakeNode("plato-letter-category"),
        direction=direction,
        objects=objects,
        bonds=bonds if bonds is not None else [],
    )


# --- length & membership ---------------------------------------------------

def test_length_is_number_of_member_objects():
    g = _group([_PosObj(0, 0), _PosObj(1, 1), _PosObj(2, 2)])
    assert g.length == 3


def test_nested_member_true_for_direct_member():
    child = _PosObj(0, 0)
    g = _group([child, _PosObj(1, 1)])
    assert g.nested_member(child) is True


def test_nested_member_true_for_recursively_nested_member():
    leaf = _PosObj(0, 0)
    inner = _group([leaf, _PosObj(1, 1)])
    outer = _group([inner, _PosObj(2, 2)])
    assert outer.nested_member(leaf) is True


def test_nested_member_false_for_non_member():
    g = _group([_PosObj(0, 0), _PosObj(1, 1)])
    assert g.nested_member(_PosObj(5, 5)) is False


# --- spanning --------------------------------------------------------------

def test_spans_whole_string_false_when_no_string():
    g = _group([_PosObj(0, 0), _PosObj(1, 1)])
    assert g.spans_whole_string() is False


def test_spans_whole_string_true_when_group_covers_all_positions():
    members = [_PosObj(0, 0), _PosObj(1, 1), _PosObj(2, 2)]
    string = FakeString(objects=list(members), length=3)
    g = _group(members, string=string)
    assert g.spans_whole_string() is True


def test_spans_whole_string_false_when_group_is_a_proper_subset():
    all_objs = [_PosObj(0, 0), _PosObj(1, 1), _PosObj(2, 2)]
    string = FakeString(objects=all_objs, length=3)
    g = _group(all_objs[:2], string=string)  # covers only 0..1
    assert g.spans_whole_string() is False


# --- internal strength -----------------------------------------------------
#
# groups.ss:392-410.  The bond factor comes from the group *category's* bond
# category — ``(tell bond-category 'get-degree-of-assoc)`` — not from the
# strengths of the constituent bonds, which is what this used to average.  The
# expected values are precomputed because the 0.98 self-weighting exponent makes
# the arithmetic non-round.

def test_internal_strength_with_no_derivable_bond_category_is_the_length_factor():
    # A category with no bond-category relation leaves the bond factor at 0, and
    # the weighted average degenerates to the length factor alone.
    g = _group([_PosObj(0, 0), _PosObj(1, 1)], category=FakeNode("plato-succgrp"))
    assert g.calculate_internal_strength() == 40.0


def test_internal_strength_letter_category_facet_uses_the_full_degree_of_assoc():
    # succ, not fully active -> degree 40; length 3 -> length factor 60.
    g = _group(
        [_PosObj(0, 0), _PosObj(1, 1), _PosObj(2, 2)],
        facet=FakeNode("plato-letter-category"),
    )
    assert g.calculate_internal_strength() == 53.0


def test_internal_strength_non_letter_facet_halves_the_degree_of_assoc():
    # Same category, but the length facet -> bond factor 40 * 1/2 = 20.
    g = _group(
        [_PosObj(0, 0), _PosObj(1, 1), _PosObj(2, 2)],
        facet=FakeNode("plato-length"),
    )
    assert g.calculate_internal_strength() == 52.0


def test_internal_strength_rises_when_the_bond_category_is_fully_active():
    # A fully-active succ shrinks its links: degree 76 rather than 40.
    g = _group(
        [_PosObj(0, 0), _PosObj(1, 1)],
        category=_category(fully_active=True),
    )
    assert g.calculate_internal_strength() == 65.0


def test_bondless_singleton_sameness_group_does_not_collapse_to_five():
    """GR-2: the bond factor exists for a singleton too.

    ``new-group`` derives the bond category from the group category, so a group
    of one has one even though it has no bonds.  Reading the factor off the
    constituent bonds gave a singleton nothing, so its internal strength was the
    bare length factor of 5 and it died at the evaluator — which forecloses the
    letter-to-group slippages and the 1-2-3 reading of ``mrrjjj``.
    """
    g = _group(
        [_PosObj(0, 0)],
        category=_category("plato-samegrp", bond_category_name="plato-sameness",
                           intrinsic_link_length=0),
    )
    assert g.calculate_internal_strength() == 92.0


# --- external strength -----------------------------------------------------

def test_external_strength_is_100_when_group_spans_string():
    members = [_PosObj(0, 0), _PosObj(1, 1)]
    string = FakeString(objects=list(members), length=2)
    g = _group(members, string=string)
    assert g.calculate_external_strength() == 100.0


def test_external_strength_zero_without_supporting_groups():
    all_objs = [_PosObj(0, 0), _PosObj(1, 1), _PosObj(2, 2)]
    string = FakeString(objects=all_objs, groups=[], length=3)
    g = _group(all_objs[:2], string=string)  # not spanning, no sibling groups
    string.groups = [g]
    assert g.calculate_external_strength() == 0.0


# --- flipping --------------------------------------------------------------

def test_flipped_version_of_sameness_group_returns_self():
    g = _group([_PosObj(0, 0), _PosObj(1, 1)], direction=None)
    assert g.make_flipped_version() is g


def test_flipped_version_of_directed_group_returns_new_group():
    g = _group(
        [_PosObj(0, 0), _PosObj(1, 1)],
        direction=FakeNode("plato-right"),
    )
    flipped = g.make_flipped_version()
    assert flipped is not g
    assert flipped.objects == g.objects


# --- constituent queries ---------------------------------------------------

def test_incompatible_groups_are_enclosing_groups_of_members():
    child = _PosObj(0, 0)
    other = _group([_PosObj(3, 3), _PosObj(4, 4)])
    child.enclosing_group = other
    g = _group([child, _PosObj(1, 1)])
    assert g.get_incompatible_groups() == [other]


def test_subobject_bridges_collects_matching_orientation():
    member = _PosObj(0, 0)
    bridge = object()
    member.horizontal_bridge = bridge
    g = _group([member, _PosObj(1, 1)])
    assert g.get_subobject_bridges("horizontal") == [bridge]


def test_get_letters_flattens_nested_membership():
    """``letters`` in ``new-group`` (groups.ss:83) — every Letter underneath,
    at any depth.  The builder's flattening branch consolidates over exactly
    this list (groups.ss:711)."""
    leaves = [_PosObj(i, i) for i in range(4)]
    inner = _group(leaves[:2])
    outer = _group([inner] + leaves[2:])
    assert outer.get_letters() == leaves


# --- local density walk ----------------------------------------------------


class _WalkObj(_PosObj):
    """A neighbour-walk participant: fixed left/right candidates, no randomness."""

    def __init__(self, left, right, *, left_n=None, right_n=None):
        super().__init__(left, right)
        self._left_n, self._right_n = left_n, right_n

    def choose_left_neighbor(self, rng=None):
        return self._left_n

    def choose_right_neighbor(self, rng=None):
        return self._right_n


def test_the_density_walk_substitutes_a_letters_enclosing_group():
    """``groups.ss:363-366`` — a walk that steps onto a grouped *letter*
    continues from the far edge of that letter's group, and counts the group.

    Not the bond version's walk (bonds.ss:137-145), which has no such
    substitution: without it a string already read as ``[m][rr][jjj]`` puts
    letters in the denominator that the reference sees as groups.
    """
    from server.engine.groups import _walk_group_neighbors

    samegrp = _category("plato-samegrp", bond_category_name="plato-sameness",
                        intrinsic_link_length=0)
    neighbour_group = _group([_PosObj(2, 2), _PosObj(3, 3)], category=samegrp)
    grouped_letter = _WalkObj(2, 2)
    grouped_letter.enclosing_group = neighbour_group
    subject = _WalkObj(0, 1, right_n=grouped_letter)

    assert _walk_group_neighbors(subject, "right") == [neighbour_group]


def test_the_density_walk_stops_at_the_end_of_the_string():
    from server.engine.groups import _walk_group_neighbors

    assert _walk_group_neighbors(_WalkObj(0, 1), "left") == []


def test_get_all_descriptions_includes_bond_descriptions():
    g = _group([_PosObj(0, 0), _PosObj(1, 1)])
    g.descriptions = ["d1"]
    g.bond_descriptions = ["bd1"]
    assert g.get_all_descriptions() == ["d1", "bd1"]
