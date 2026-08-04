"""Unit tests for engine.workspace.WorkspaceString.

WorkspaceString only needs ``slipnet.nodes.get(name)`` to build its letters, so
a trivial fake slipnet fully isolates it from the database and the rest of the
engine. Bonds and groups are real engine objects (their own logic is tested
elsewhere) constructed over the string's letters; slipnet nodes are faked.
No randomness is involved.
"""

import pytest

from server.engine.bonds import Bond
from server.engine.groups import Group
from server.engine.workspace import WorkspaceString

from tests.unit._fakes import FakeNode


class _FakeSlipnet:
    """Provides only the ``.nodes`` mapping WorkspaceString reads."""

    def __init__(self):
        self.nodes = {}


class _RightBond:
    """A minimal object occupying a letter's right-bond slot for relevance."""

    def __init__(self, bond_category=None, direction=None):
        self.bond_category = bond_category
        self.direction = direction


def _string(text="abc", string_type="initial"):
    return WorkspaceString(text, _FakeSlipnet(), string_type)


def _bond(frm, to, *, category=None, direction=None):
    return Bond(
        from_object=frm,
        to_object=to,
        bond_category=category or FakeNode("plato-successor"),
        bond_facet=FakeNode("plato-letter-category"),
        from_descriptor=FakeNode("plato-a"),
        to_descriptor=FakeNode("plato-b"),
        direction=direction,
    )


def _group(objs, string, *, category=None, direction=None):
    return Group(
        string=string,
        group_category=category or FakeNode("plato-successor-group"),
        bond_facet=FakeNode("plato-letter-category"),
        direction=direction,
        objects=objs,
        bonds=[],
    )


# --- basic accessors -------------------------------------------------------

def test_length_is_text_length():
    assert _string("abc").length == 3


def test_letters_returns_only_letter_objects():
    s = _string("abc")
    assert len(s.letters) == 3


def test_get_object_at_returns_object_covering_position():
    s = _string("abc")
    assert s.get_object_at(1) is s.objects[1]


def test_get_object_at_returns_none_beyond_the_string():
    s = _string("abc")
    assert s.get_object_at(9) is None


# --- bond management -------------------------------------------------------

def test_add_bond_links_adjacent_letters():
    s = _string("abc")
    l0, l1 = s.objects[0], s.objects[1]
    bond = _bond(l0, l1)
    s.add_bond(bond)
    assert bond in s.bonds
    assert l0.right_bond is bond
    assert l1.left_bond is bond


def test_add_bond_refuses_an_occupied_right_slot():
    """``build-bond`` (bonds.ss:410-422) is reached only after ``bond-builder``
    has broken every bond it displaced.  Overwriting an occupied slot leaves the
    displaced bond listed as built with both its pointers naming someone else's
    bond — a corrupt string whose symptoms show up far from the cause."""
    s = _string("abc")
    l0, l1 = s.objects[0], s.objects[1]
    s.add_bond(_bond(l0, l1))
    with pytest.raises(AssertionError, match="right slot"):
        s.add_bond(_bond(l0, l1, category=FakeNode("plato-sameness")))


def test_add_bond_refuses_an_occupied_left_slot():
    s = _string("abc")
    l0, l1, l2 = s.objects[0], s.objects[1], s.objects[2]
    s.add_bond(_bond(l1, l2))
    # A bond from l2 leftwards would want l2's left slot, already held.
    conflicting = _bond(l1, l2, category=FakeNode("plato-sameness"))
    conflicting.left_object.right_bond = None  # free the right slot only
    with pytest.raises(AssertionError, match="left slot"):
        s.add_bond(conflicting)


def test_add_bond_accepts_re_adding_the_same_bond():
    """Idempotent for the bond already in the slot — it is not its own conflict."""
    s = _string("abc")
    bond = _bond(s.objects[0], s.objects[1])
    s.add_bond(bond)
    s.add_bond(bond)


def test_remove_bond_detaches_it_from_objects():
    s = _string("abc")
    l0, l1 = s.objects[0], s.objects[1]
    bond = _bond(l0, l1)
    s.add_bond(bond)
    s.remove_bond(bond)
    assert bond not in s.bonds
    assert l0.right_bond is None
    assert l1.left_bond is None


# --- group management ------------------------------------------------------

def test_add_group_sets_enclosing_group_on_members():
    s = _string("abc")
    members = [s.objects[0], s.objects[1]]
    group = _group(members, s)
    s.add_group(group)
    assert group in s.groups
    assert members[0].enclosing_group is group


def test_remove_group_clears_enclosing_group_on_members():
    s = _string("abc")
    members = [s.objects[0], s.objects[1]]
    group = _group(members, s)
    s.add_group(group)
    s.remove_group(group)
    assert group not in s.groups
    assert members[0].enclosing_group is None


# --- counting --------------------------------------------------------------

def test_average_intra_unhappiness_zero_for_empty_string():
    assert _string("").get_average_intra_string_unhappiness() == 0.0


def test_average_intra_unhappiness_is_mean_over_objects():
    s = _string("ab")
    s.objects[0].intra_string_unhappiness = 40.0
    s.objects[1].intra_string_unhappiness = 60.0
    assert s.get_average_intra_string_unhappiness() == 50.0


def test_average_intra_unhappiness_is_rounded():
    """``workspace-strings.ss:336-338`` wraps the mean in ``round``.

    Three objects rarely average to a whole number, and this value is a
    selection weight for ``choose-string``.
    """
    s = _string("abc")
    s.objects[0].intra_string_unhappiness = 40.0
    s.objects[1].intra_string_unhappiness = 60.0
    s.objects[2].intra_string_unhappiness = 61.0
    # (40 + 60 + 61) / 3 = 53.666...
    assert s.get_average_intra_string_unhappiness() == 54.0


# --- equivalence -----------------------------------------------------------

def test_bond_present_true_for_equivalent_bond():
    s = _string("abc")
    cat = FakeNode("plato-successor")
    s.add_bond(_bond(s.objects[0], s.objects[1], category=cat))
    query = _bond(s.objects[0], s.objects[1], category=cat)
    assert s.bond_present(query) is True


def test_bond_present_ignores_the_facet():
    """``get-equivalent-bond`` (workspace-strings.ss:129-137) compares from-object,
    to-object, category and direction — and deliberately *not* the facet.

    A length-facet sameness bond between the same pair says the same thing about
    the string as the letter-category one; requiring the facet to match too let
    both be built, and the pair then counted twice in support and density.
    """
    s = _string("abc")
    cat = FakeNode("plato-sameness")
    built = _bond(s.objects[0], s.objects[1], category=cat)
    s.add_bond(built)

    twin = _bond(s.objects[0], s.objects[1], category=cat)
    twin.bond_facet = FakeNode("plato-length")
    assert s.bond_present(twin) is True


def test_bond_present_false_when_direction_differs():
    """Direction *is* part of the equivalence."""
    s = _string("abc")
    cat = FakeNode("plato-successor")
    s.add_bond(
        _bond(s.objects[0], s.objects[1], category=cat, direction=FakeNode("plato-right"))
    )
    query = _bond(
        s.objects[0], s.objects[1], category=cat, direction=FakeNode("plato-left")
    )
    assert s.bond_present(query) is False


def test_get_equivalent_bond_none_when_category_differs():
    s = _string("abc")
    s.add_bond(_bond(s.objects[0], s.objects[1], category=FakeNode("plato-successor")))
    query = _bond(s.objects[0], s.objects[1], category=FakeNode("plato-sameness"))
    assert s.get_equivalent_bond(query) is None


def test_group_present_true_for_equivalent_group():
    s = _string("abc")
    cat = FakeNode("plato-successor-group")
    s.add_group(_group([s.objects[0], s.objects[1]], s, category=cat))
    query = _group([s.objects[0], s.objects[1]], s, category=cat)
    assert s.group_present(query) is True


def test_get_equivalent_group_none_when_category_differs():
    s = _string("abc")
    s.add_group(_group([s.objects[0], s.objects[1]], s, category=FakeNode("plato-successor-group")))
    query = _group([s.objects[0], s.objects[1]], s, category=FakeNode("plato-sameness-group"))
    assert s.get_equivalent_group(query) is None


# --- spanning --------------------------------------------------------------

def test_spanning_group_exists_true_when_group_covers_string():
    s = _string("ab")
    s.add_group(_group([s.objects[0], s.objects[1]], s))
    assert s.spanning_group_exists() is True


def test_spanning_group_exists_false_without_spanning_group():
    s = _string("abc")
    s.add_group(_group([s.objects[0], s.objects[1]], s))  # covers 0..1 of 0..2
    assert s.spanning_group_exists() is False


# --- relevance -------------------------------------------------------------

def test_bond_category_relevance_zero_with_at_most_one_nonspanning_object():
    # A single-letter string: the letter spans the whole string, so there are
    # no non-spanning objects to compare -> relevance is 0.
    assert _string("a").get_bond_category_relevance(FakeNode("plato-successor")) == 0.0


def test_bond_category_relevance_is_fraction_of_matching_right_bonds():
    s = _string("abc")
    cat = FakeNode("plato-successor")
    s.objects[0].right_bond = _RightBond(bond_category=cat)
    s.objects[1].right_bond = _RightBond(bond_category=cat)
    # 3 non-spanning objects; 2 have a matching right bond -> 100*2/(3-1) = 100
    assert s.get_bond_category_relevance(cat) == 100.0


def test_direction_relevance_is_fraction_of_matching_right_bonds():
    s = _string("abc")
    direction = FakeNode("plato-right")
    s.objects[0].right_bond = _RightBond(direction=direction)
    # 3 non-spanning objects; 1 matches -> round(100*1/2) = 50
    assert s.get_direction_relevance(direction) == 50.0
