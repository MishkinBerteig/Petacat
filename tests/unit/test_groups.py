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


class _FakeBond:
    def __init__(self, strength):
        self.strength = strength


def _group(objects, *, bonds=None, facet=None, direction=None, string=None,
           category=None):
    return Group(
        string=string,
        group_category=category or FakeNode("plato-successor-group", short_name="succ-grp"),
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

def test_internal_strength_with_no_bonds_is_the_length_factor():
    # length 2 -> length factor 40; no bonds -> returns length factor directly
    g = _group([_PosObj(0, 0), _PosObj(1, 1)], bonds=[])
    assert g.calculate_internal_strength() == 40.0


def test_internal_strength_length_factor_for_three_members():
    # length 3 -> length factor 60; no bonds
    g = _group([_PosObj(0, 0), _PosObj(1, 1), _PosObj(2, 2)], bonds=[])
    assert g.calculate_internal_strength() == 60.0


def test_internal_strength_letter_category_facet_uses_full_bond_factor():
    # length 2 (lf 40), two bonds of strength 60, letter-category facet.
    # bond_factor = 60; strength = 0.2*60^0.98 + 40 = 51 (precomputed).
    g = _group(
        [_PosObj(0, 0), _PosObj(1, 1)],
        bonds=[_FakeBond(60), _FakeBond(60)],
        facet=FakeNode("plato-letter-category"),
    )
    assert g.calculate_internal_strength() == 51.0


def test_internal_strength_non_letter_facet_halves_bond_factor():
    # Same bonds but a length facet -> bond_factor = 60*0.5 = 30 -> strength 37.
    g = _group(
        [_PosObj(0, 0), _PosObj(1, 1)],
        bonds=[_FakeBond(60), _FakeBond(60)],
        facet=FakeNode("plato-length"),
    )
    assert g.calculate_internal_strength() == 37.0


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


def test_get_all_descriptions_includes_bond_descriptions():
    g = _group([_PosObj(0, 0), _PosObj(1, 1)])
    g.descriptions = ["d1"]
    g.bond_descriptions = ["bd1"]
    assert g.get_all_descriptions() == ["d1", "bd1"]
