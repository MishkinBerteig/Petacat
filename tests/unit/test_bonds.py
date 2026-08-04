"""Unit tests for engine.bonds.Bond.

Each test isolates one path through the Bond strength / support / geometry
logic. Positional workspace objects and strings are represented by tiny local
fakes (Bond geometry needs left/right string positions and bond slots, which
the generic fakes don't carry). Slipnet nodes come from the shared fakes.
No randomness is involved.

The density tests are the exception: ``get-local-density`` walks *positional*
neighbours, which is behaviour of the real ``WorkspaceObject``, so those build a
real ``WorkspaceString`` over a slipnet faked down to its ``.nodes`` mapping.
"""

from server.engine.bonds import Bond
from server.engine.groups import Group
from server.engine.workspace import WorkspaceString

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


# --- local density: positional slots, bonded or not ------------------------
#
# Scheme: ``get-local-density`` (bonds.ss:136-160).  The walk steps through
# positional neighbours and counts every step as a bond slot; 100 is reached only
# when the walk finds no slots at all.  Following ``left_bond``/``right_bond``
# instead stopped at the first *unbonded* object, keeping unbonded slots out of
# the denominator entirely, and returned 100 for a bond with no neighbours bonded
# at all.


class _FakeSlipnet:
    """Provides only the ``.nodes`` mapping ``WorkspaceString`` reads."""

    def __init__(self):
        self.nodes = {}


def _real_string(text):
    return WorkspaceString(text, _FakeSlipnet(), "initial")


def _succ_bond(string, left_index, right_index, category, direction):
    bond = _bond(
        string.objects[left_index],
        string.objects[right_index],
        category,
        _letter_category(),
        direction=direction,
    )
    bond.proposal_level = Bond.BUILT
    string.add_bond(bond)
    return bond


def test_local_density_counts_unbonded_positional_slots():
    """The audit's worked example: ``abcdef`` with only ``a-b`` built, ``c-d``
    proposed.  Four slots (b, a to the left of c; e, f to the right of d), one of
    which — a's right slot, holding a-b — carries a matching bond.  100*1/4 = 25.
    """
    string = _real_string("abcdef")
    successor = _successor()
    right = FakeNode("plato-right")
    _succ_bond(string, 0, 1, successor, right)

    proposed = _bond(string.objects[2], string.objects[3], successor,
                     _letter_category(), direction=right)
    assert proposed.get_local_density() == 25.0


def test_local_support_of_a_lone_early_bond_is_30_not_60():
    """Support = round(100*sqrt(density/100) * 0.6^(1/n^3)) with n = 1.

    density 25 -> 100*0.5 = 50, times 0.6 -> 30.  Walking bond pointers gave
    density 100 and so support 60: sparse early bonds snowballed on a denominator
    of zero.
    """
    string = _real_string("abcdef")
    successor = _successor()
    right = FakeNode("plato-right")
    _succ_bond(string, 0, 1, successor, right)

    proposed = _bond(string.objects[2], string.objects[3], successor,
                     _letter_category(), direction=right)
    assert proposed.get_num_of_local_supporting_bonds() == 1
    assert proposed.calculate_external_strength() == 30.0


def test_local_density_is_100_only_when_the_bond_spans_the_string():
    """``(if (zero? num-of-bond-slots) 100 ...)`` — the walk has nowhere to go."""
    string = _real_string("ab")
    successor = _successor()
    right = FakeNode("plato-right")
    proposed = _bond(string.objects[0], string.objects[1], successor,
                     _letter_category(), direction=right)
    assert proposed.get_local_density() == 100.0


def test_local_density_ignores_a_neighbour_bond_of_another_category():
    """The neighbour slots are counted; only *matching* bonds fill them."""
    string = _real_string("abcdef")
    successor = _successor()
    right = FakeNode("plato-right")
    _succ_bond(string, 0, 1, _sameness(), None)

    proposed = _bond(string.objects[2], string.objects[3], successor,
                     _letter_category(), direction=right)
    assert proposed.get_local_density() == 0.0


# --- which generator the walk draws from ------------------------------------
#
# Every step of the walk is a salience-weighted stochastic pick among the objects
# edged at the adjacent position, so a position offering two candidates — a letter
# and the group edged there — is a draw.  The generator is threaded from the call
# site (``update_strength(rng)``) rather than read off the Workspace, so that under
# free-running the walk consumes the executing codelet's own stream.


class _RecordingRNG:
    """Only the one method the neighbour pick calls."""

    def __init__(self):
        self.picks = 0

    def weighted_pick(self, items, weights):
        self.picks += 1
        return items[0]


def test_update_strength_hands_its_rng_to_the_density_walk():
    string = _real_string("mrrjjj")
    rr = Group(
        string=string,
        group_category=FakeNode("plato-same-group"),
        bond_facet=_letter_category(),
        direction=None,
        objects=[string.objects[1], string.objects[2]],
        bonds=[],
    )
    rr.proposal_level = Group.BUILT
    string.add_group(rr)

    sameness = _sameness()
    # One disjoint supporting bond, so local support gets as far as the density
    # walk instead of short-circuiting to 0.
    _succ_bond(string, 4, 5, sameness, None)
    proposed = _bond(string.objects[3], string.objects[4], sameness,
                     _letter_category())

    rng = _RecordingRNG()
    proposed.update_strength(rng)

    # Walking left from the first ``j`` reaches position 2, where both the letter
    # ``r`` and the group ``[rr]`` are edged: two candidates, so a real draw.
    assert rng.picks > 0


def test_the_density_walk_asks_no_one_else_for_a_generator():
    """Given none, it takes the first candidate rather than finding one.

    The generator used to be hung off the Workspace and read from here, which is
    how the walk came to bypass the per-codelet streams free-running derives.
    """
    string = _real_string("mrrjjj")
    rr = Group(
        string=string,
        group_category=FakeNode("plato-same-group"),
        bond_facet=_letter_category(),
        direction=None,
        objects=[string.objects[1], string.objects[2]],
        bonds=[],
    )
    rr.proposal_level = Group.BUILT
    string.add_group(rr)

    class _Workspace:
        def __getattr__(self, name):  # pragma: no cover - must never be reached
            raise AssertionError(f"the density walk reached the Workspace for {name!r}")

    string.workspace = _Workspace()

    sameness = _sameness()
    _succ_bond(string, 4, 5, sameness, None)
    proposed = _bond(string.objects[3], string.objects[4], sameness,
                     _letter_category())

    # No generator, no exception, and the same answer every time.
    assert proposed.get_local_density() == proposed.get_local_density()


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
