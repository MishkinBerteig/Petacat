"""Unit tests for engine.bonds.Bond.

Each test isolates one path through the Bond strength / support / geometry
logic. Positional workspace objects and strings are represented by tiny local
fakes (Bond geometry needs left/right string positions and bond slots, which
the generic fakes don't carry). Slipnet nodes come from the shared fakes.
No randomness is involved.
"""

from server.engine.bonds import Bond

from tests.unit._fakes import FakeNode


class _Obj:
    """A positional workspace object (letter unless ``is_group``)."""

    def __init__(self, left, right, *, string=None, is_group=False):
        self.left_string_pos = left
        self.right_string_pos = right
        self.string = string
        self.left_bond = None
        self.right_bond = None
        if is_group:
            self.objects = []  # presence of ``objects`` marks it a group


class _Str:
    def __init__(self, bonds=None):
        self.bonds = bonds if bonds is not None else []


def _sameness():
    return FakeNode("plato-sameness", short_name="same", intrinsic_link_length=0)


def _successor():
    return FakeNode("plato-successor", short_name="succ", intrinsic_link_length=60)


def _letter_category():
    return FakeNode("plato-letter-category")


def _length():
    return FakeNode("plato-length")


def _bond(from_obj, to_obj, category, facet, direction=None):
    return Bond(
        from_object=from_obj,
        to_object=to_obj,
        bond_category=category,
        bond_facet=facet,
        from_descriptor=FakeNode("plato-a"),
        to_descriptor=FakeNode("plato-b"),
        direction=direction,
    )


# --- left / right geometry -------------------------------------------------

def test_left_object_is_from_object_when_it_is_leftmost():
    a, b = _Obj(0, 0), _Obj(1, 1)
    bond = _bond(a, b, _sameness(), _letter_category())
    assert bond.left_object is a


def test_left_object_is_to_object_when_from_object_is_rightmost():
    a, b = _Obj(2, 2), _Obj(0, 0)
    bond = _bond(a, b, _sameness(), _letter_category())
    assert bond.left_object is b


# --- directed --------------------------------------------------------------

def test_directed_true_when_direction_present():
    bond = _bond(_Obj(0, 0), _Obj(1, 1), _successor(), _letter_category(),
                 direction=FakeNode("plato-right"))
    assert bond.directed is True


def test_directed_false_when_direction_none():
    bond = _bond(_Obj(0, 0), _Obj(1, 1), _sameness(), _letter_category())
    assert bond.directed is False


# --- structural equality ---------------------------------------------------

def test_bonds_equal_true_for_matching_objects_category_direction():
    a, b = _Obj(0, 0), _Obj(1, 1)
    cat = _sameness()
    assert _bond(a, b, cat, _letter_category()).bonds_equal(_bond(a, b, cat, _letter_category()))


def test_bonds_equal_false_when_category_differs():
    a, b = _Obj(0, 0), _Obj(1, 1)
    b1 = _bond(a, b, _sameness(), _letter_category())
    b2 = _bond(a, b, _successor(), _letter_category())
    assert b1.bonds_equal(b2) is False


# --- bond degree of association (one path per link-length case) -------------

def test_degree_of_assoc_sameness_is_100():
    bond = _bond(_Obj(0, 0), _Obj(1, 1), _sameness(), _letter_category())
    # intrinsic_link_length 0 -> raw 100 -> 11*sqrt(100)=110 -> capped 100
    assert bond._bond_degree_of_assoc() == 100.0


def test_degree_of_assoc_successor_is_70_when_the_category_is_not_fully_active():
    bond = _bond(_Obj(0, 0), _Obj(1, 1), _successor(), _letter_category())
    # intrinsic_link_length 60 -> raw 40 -> round(11*sqrt(40)) = 70
    assert bond._bond_degree_of_assoc() == 70.0


def test_degree_of_assoc_successor_rises_to_96_when_the_category_is_fully_active():
    """Scheme: slipnet.ss:90-91 — a fully-active concept shrinks its links, so it
    associates what it labels more strongly.  60 -> shrunk 24 -> raw 76 ->
    round(11*sqrt(76)) = 96."""
    cat = FakeNode(
        "plato-successor", short_name="succ", intrinsic_link_length=60, fully_active=True
    )
    bond = _bond(_Obj(0, 0), _Obj(1, 1), cat, _letter_category())
    assert bond._bond_degree_of_assoc() == 96.0


def test_degree_of_assoc_is_zero_when_link_length_none():
    cat = FakeNode("plato-sameness", intrinsic_link_length=None)
    bond = _bond(_Obj(0, 0), _Obj(1, 1), cat, _letter_category())
    # ``SlipnetNode.degree_of_assoc`` (slipnet.ss:90-91) has nothing to subtract
    # from 100 without a link length, so the association is 0.  Unreachable for a
    # real bond: sameness, successor and predecessor all carry link lengths.
    assert bond._bond_degree_of_assoc() == 0.0


# --- internal strength (compatibility * facet * assoc) ---------------------

def test_internal_strength_letters_sameness_letter_category():
    bond = _bond(_Obj(0, 0), _Obj(1, 1), _sameness(), _letter_category())
    # 1.0 (same type) * 1.0 (letter-category) * 100 = 100
    assert bond.calculate_internal_strength() == 100.0


def test_internal_strength_length_facet_applies_0_7_factor():
    bond = _bond(_Obj(0, 0), _Obj(1, 1), _successor(), _length())
    # 1.0 * 0.7 (length facet) * 70 (successor assoc) = 49
    assert bond.calculate_internal_strength() == 49.0


def test_internal_strength_mixed_letter_and_group_applies_0_7_compat():
    letter = _Obj(0, 0)
    group = _Obj(1, 2, is_group=True)
    bond = _bond(letter, group, _sameness(), _letter_category())
    # 0.7 (mixed type) * 1.0 * 100 = 70
    assert bond.calculate_internal_strength() == 70.0


# --- external strength / local support -------------------------------------

def test_external_strength_zero_when_no_supporting_bonds():
    string = _Str(bonds=[])
    a, b = _Obj(0, 0, string=string), _Obj(1, 1, string=string)
    bond = _bond(a, b, _sameness(), _letter_category())
    string.bonds = [bond]
    assert bond.calculate_external_strength() == 0.0


def test_num_supporting_bonds_counts_matching_built_disjoint_bond():
    string = _Str()
    cat = _sameness()
    a, b = _Obj(0, 0, string=string), _Obj(1, 1, string=string)
    self_bond = _bond(a, b, cat, _letter_category())
    c, d = _Obj(2, 2, string=string), _Obj(3, 3, string=string)
    other = _bond(c, d, cat, _letter_category())
    other.proposal_level = Bond.BUILT
    string.bonds = [self_bond, other]
    assert self_bond.get_num_of_local_supporting_bonds() == 1


def test_num_supporting_bonds_ignores_unbuilt_bond():
    string = _Str()
    cat = _sameness()
    a, b = _Obj(0, 0, string=string), _Obj(1, 1, string=string)
    self_bond = _bond(a, b, cat, _letter_category())
    c, d = _Obj(2, 2, string=string), _Obj(3, 3, string=string)
    other = _bond(c, d, cat, _letter_category())  # left at PROPOSED
    string.bonds = [self_bond, other]
    assert self_bond.get_num_of_local_supporting_bonds() == 0


def test_num_supporting_bonds_ignores_different_category():
    string = _Str()
    a, b = _Obj(0, 0, string=string), _Obj(1, 1, string=string)
    self_bond = _bond(a, b, _sameness(), _letter_category())
    c, d = _Obj(2, 2, string=string), _Obj(3, 3, string=string)
    other = _bond(c, d, _successor(), _letter_category())
    other.proposal_level = Bond.BUILT
    string.bonds = [self_bond, other]
    assert self_bond.get_num_of_local_supporting_bonds() == 0


# --- incompatible (slot-conflicting) bonds ---------------------------------

def test_incompatible_bonds_returns_slot_conflicts():
    a, b = _Obj(0, 0), _Obj(1, 1)
    bond = _bond(a, b, _sameness(), _letter_category())
    left_conflict = _bond(_Obj(0, 0), _Obj(1, 1), _successor(), _letter_category())
    right_conflict = _bond(_Obj(0, 0), _Obj(1, 1), _successor(), _letter_category())
    a.right_bond = left_conflict   # left_object's right slot
    b.left_bond = right_conflict   # right_object's left slot
    result = bond.get_incompatible_bonds()
    assert left_conflict in result and right_conflict in result


# --- flipped ---------------------------------------------------------------

def test_flipped_swaps_objects_and_descriptors():
    a, b = _Obj(0, 0), _Obj(1, 1)
    fd, td = FakeNode("plato-a"), FakeNode("plato-b")
    bond = Bond(a, b, _sameness(), _letter_category(), fd, td)
    flipped = bond.flipped()
    assert flipped.from_object is b
    assert flipped.to_object is a
    assert flipped.from_descriptor is td
    assert flipped.to_descriptor is fd
