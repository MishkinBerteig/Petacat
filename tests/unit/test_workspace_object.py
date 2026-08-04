"""Tests for WorkspaceObject and Letter.

The first three tests exercise construction and the legacy salience shim; the
rest isolate one path each through the object's geometry, bond bookkeeping,
importance, unhappiness, and bridge-weakness logic. Collaborators (string,
bonds, bridges, descriptions) are lightweight fakes so no path depends on the
full engine or the database. No randomness is involved.
"""

from server.engine.groups import Group
from server.engine.rng import RNG
from server.engine.workspace import WorkspaceString
from server.engine.workspace_objects import Letter, WorkspaceObject
from server.engine.slipnet import SlipnetNode

from tests.unit._fakes import FakeNode, FakeString


class _FakeSlipnet:
    """Provides only the ``.nodes`` mapping ``WorkspaceString`` reads."""

    def __init__(self):
        self.nodes = {}


def test_letter_creation():
    node = SlipnetNode("plato-a", "a", 10)
    letter = Letter(string=None, position=0, letter_category=node)
    assert letter.left_string_pos == 0
    assert letter.right_string_pos == 0
    assert letter.span == 1


def test_initial_unhappiness():
    node = SlipnetNode("plato-a", "a", 10)
    letter = Letter(string=None, position=0, letter_category=node)
    assert letter.intra_string_unhappiness == 100.0


def test_salience_update():
    node = SlipnetNode("plato-a", "a", 10)
    letter = Letter(string=None, position=0, letter_category=node)
    letter.relative_importance = 50
    letter.intra_string_unhappiness = 80
    letter.update_salience()
    # intra: 0.8*80 + 0.2*50 = 74
    assert letter.salience["intra"] == 74


# ---- test doubles ---------------------------------------------------------

class _FakeBond:
    def __init__(self, strength, category_name="plato-successor"):
        self.strength = strength
        self.bond_category = FakeNode(category_name)


class _FakeBridge:
    def __init__(self, strength):
        self.strength = strength


class _FakeDesc:
    def __init__(self, *, descriptor_activation=0.0, description_type=None,
                 descriptor=None, relevant=True):
        self.descriptor_activation = descriptor_activation
        self.description_type = description_type
        self.descriptor = descriptor
        self._relevant = relevant

    def is_relevant(self):
        return self._relevant


# ---- geometry / position predicates ---------------------------------------

def test_span_counts_positions_inclusively():
    obj = WorkspaceObject(string=None, left_pos=2, right_pos=5)
    assert obj.span == 4


def test_spans_whole_string_false_when_no_string():
    obj = WorkspaceObject(string=None, left_pos=0, right_pos=2)
    assert obj.spans_whole_string() is False


def test_spans_whole_string_true_when_span_equals_string_length():
    string = FakeString(length=3)
    obj = WorkspaceObject(string=string, left_pos=0, right_pos=2)
    assert obj.spans_whole_string() is True


def test_leftmost_in_string_true_at_position_zero():
    obj = WorkspaceObject(string=None, left_pos=0, right_pos=0)
    assert obj.leftmost_in_string() is True


def test_leftmost_in_string_false_when_not_at_zero():
    obj = WorkspaceObject(string=None, left_pos=1, right_pos=1)
    assert obj.leftmost_in_string() is False


def test_rightmost_in_string_true_at_last_position():
    string = FakeString(length=3)
    obj = WorkspaceObject(string=string, left_pos=2, right_pos=2)
    assert obj.rightmost_in_string() is True


def test_rightmost_in_string_false_when_no_string():
    obj = WorkspaceObject(string=None, left_pos=2, right_pos=2)
    assert obj.rightmost_in_string() is False


# ---- middle-in-string?  (workspace-objects.ss:364-370) --------------------
#
# The reference asks about *neighbours*, not about indices:
#
#     (and (exists? left-neighbor) (exists? right-neighbor)
#          (tell left-neighbor 'leftmost-in-string?)
#          (tell right-neighbor 'rightmost-in-string?))
#
# where the neighbours are the *ungrouped* ones, so the test reaches past a
# letter swallowed by a group to the group itself.  Two consequences that index
# arithmetic gets wrong in opposite directions are pinned below: a group can be
# middle, and the centre letter of a five-letter string is not.

def _string_of(letters, groups=()):
    """A string container holding *letters* and *groups*, as the neighbour walk
    reads it: ``letters`` positionally, ``groups`` by edge position."""
    return FakeString(
        objects=list(letters) + list(groups),
        letters=list(letters),
        groups=list(groups),
        length=len(letters),
    )


def _letters(n, string=None):
    objs = [WorkspaceObject(string=string, left_pos=i, right_pos=i) for i in range(n)]
    return objs


def _spanning(string, left, right, members):
    """A group-like object over [left, right] that owns *members*."""
    group = WorkspaceObject(string=string, left_pos=left, right_pos=right)
    group.objects = members          # having ``objects`` is what makes it a group
    group.nested_member = lambda other, _m=members: other in _m
    for member in members:
        member.enclosing_group = group
    return group


def test_middle_in_string_true_for_the_centre_letter_of_three():
    letters = _letters(3)
    string = _string_of(letters)
    for letter in letters:
        letter.string = string
    assert letters[1].middle_in_string() is True


def test_middle_in_string_false_for_an_edge_letter():
    letters = _letters(3)
    string = _string_of(letters)
    for letter in letters:
        letter.string = string
    assert letters[0].middle_in_string() is False
    assert letters[2].middle_in_string() is False


def test_middle_in_string_false_for_the_centre_letter_of_five():
    """``c`` in ``abcde`` is at the centre and is *not* middle.

    Its ungrouped neighbours are ``b`` and ``d``, and ``middle-in-string?``
    requires the neighbours to *be* the edge objects — ``b`` is not leftmost and
    ``d`` is not rightmost.  "Middle" in Metacat means *flanked by the ends*, not
    *at the centre*, which is why a five-letter string has no middle letter at
    all until grouping gives one edge-to-edge neighbours.
    """
    letters = _letters(5)
    string = _string_of(letters)
    for letter in letters:
        letter.string = string
    assert letters[2].middle_in_string() is False


def test_a_group_between_two_edge_objects_is_middle():
    """``mrrjjj`` read as ``[m][rr][jjj]``: the ``[rr]`` group is middle.

    Its ungrouped left neighbour is the letter ``m`` (leftmost) and its ungrouped
    right neighbour is the group ``[jjj]`` (rightmost) — the letter ``j`` at
    position 3 is skipped, being enclosed in a group that does not contain
    ``[rr]``.  This is the description that earns the ``b→[rr]`` vertical bridge
    its distinguishing ``middle⇒middle`` concept-mapping in ``abc→abd;
    mrrjjj→?``, and it is unreachable by any test phrased in indices.
    """
    letters = _letters(6)
    string = _string_of(letters)
    for letter in letters:
        letter.string = string
    rr = _spanning(string, 1, 2, letters[1:3])
    jjj = _spanning(string, 3, 6 - 1, letters[3:])
    string.objects.extend([rr, jjj])
    string.groups.extend([rr, jjj])

    assert rr.middle_in_string() is True
    assert jjj.middle_in_string() is False
    assert letters[0].middle_in_string() is False


def test_middle_in_string_false_when_a_neighbour_is_missing():
    letters = _letters(2)
    string = _string_of(letters)
    for letter in letters:
        letter.string = string
    assert letters[0].middle_in_string() is False
    assert letters[1].middle_in_string() is False


def test_get_nesting_level_counts_enclosing_chain():
    inner = WorkspaceObject(string=None, left_pos=0, right_pos=1)
    outer = WorkspaceObject(string=None, left_pos=0, right_pos=2)
    inner.enclosing_group = outer
    assert inner.get_nesting_level() == 1


# ---- bridge mapping predicate ---------------------------------------------

def test_mapped_vertical_true_when_vertical_bridge_present():
    obj = WorkspaceObject(string=None, left_pos=0, right_pos=0)
    obj.vertical_bridge = _FakeBridge(50)
    assert obj.mapped("vertical") is True


def test_mapped_both_false_when_only_one_bridge_present():
    obj = WorkspaceObject(string=None, left_pos=0, right_pos=0)
    obj.horizontal_bridge = _FakeBridge(50)
    assert obj.mapped("both") is False


# ---- bond bookkeeping -----------------------------------------------------

def test_get_incident_bonds_includes_left_and_right():
    obj = WorkspaceObject(string=None, left_pos=1, right_pos=1)
    left, right = _FakeBond(50), _FakeBond(60)
    obj.left_bond = left
    obj.right_bond = right
    assert obj.get_incident_bonds() == [left, right]


def test_outgoing_sameness_bond_is_mirrored_as_incoming():
    obj = WorkspaceObject(string=None, left_pos=0, right_pos=0)
    bond = _FakeBond(50, category_name="plato-sameness")
    obj.add_outgoing_bond(bond)
    assert bond in obj.incoming_bonds  # sameness bonds are symmetric


def test_outgoing_non_sameness_bond_is_not_mirrored():
    obj = WorkspaceObject(string=None, left_pos=0, right_pos=0)
    bond = _FakeBond(50, category_name="plato-successor")
    obj.add_outgoing_bond(bond)
    assert bond not in obj.incoming_bonds


def test_remove_outgoing_bond_removes_it():
    obj = WorkspaceObject(string=None, left_pos=0, right_pos=0)
    bond = _FakeBond(50, category_name="plato-successor")
    obj.add_outgoing_bond(bond)
    obj.remove_outgoing_bond(bond)
    assert bond not in obj.outgoing_bonds


# ---- description predicates -----------------------------------------------

def test_description_type_present_true_when_matching_type():
    dtype = FakeNode("plato-letter-category")
    obj = WorkspaceObject(string=None, left_pos=0, right_pos=0)
    obj.descriptions = [_FakeDesc(description_type=dtype)]
    assert obj.description_type_present(dtype) is True


def test_descriptor_present_false_when_absent():
    obj = WorkspaceObject(string=None, left_pos=0, right_pos=0)
    obj.descriptions = [_FakeDesc(descriptor=FakeNode("plato-a"))]
    assert obj.descriptor_present(FakeNode("plato-z")) is False


# ---- importance -----------------------------------------------------------

def test_update_importance_sums_relevant_descriptor_activation():
    obj = WorkspaceObject(string=None, left_pos=0, right_pos=0)
    obj.descriptions = [
        _FakeDesc(descriptor_activation=30.0),
        _FakeDesc(descriptor_activation=40.0),
    ]
    obj.update_importance()
    assert obj.raw_importance == 70.0


def test_update_importance_caps_at_max_raw():
    obj = WorkspaceObject(string=None, left_pos=0, right_pos=0)
    obj.descriptions = [_FakeDesc(descriptor_activation=500.0)]
    obj.update_importance(max_raw=300.0)
    assert obj.raw_importance == 300.0


def test_update_importance_scaled_down_when_enclosed():
    obj = WorkspaceObject(string=None, left_pos=0, right_pos=0)
    obj.enclosing_group = WorkspaceObject(string=None, left_pos=0, right_pos=1)
    obj.descriptions = [_FakeDesc(descriptor_activation=100.0)]
    obj.update_importance(max_raw=300.0, enclosed_factor=0.5)
    assert obj.raw_importance == 50.0


# ---- intra-string unhappiness ---------------------------------------------

def test_intra_unhappiness_zero_when_object_spans_string():
    string = FakeString(length=3)
    obj = WorkspaceObject(string=string, left_pos=0, right_pos=2)
    obj.update_intra_string_unhappiness()
    assert obj.intra_string_unhappiness == 0.0


def test_intra_unhappiness_full_when_no_incident_bonds():
    string = FakeString(length=3)
    obj = WorkspaceObject(string=string, left_pos=1, right_pos=1)
    obj.update_intra_string_unhappiness()
    assert obj.intra_string_unhappiness == 100.0


def test_intra_unhappiness_edge_object_subtracts_third_of_bond_strength():
    string = FakeString(length=3)
    obj = WorkspaceObject(string=string, left_pos=0, right_pos=0)  # leftmost
    obj.right_bond = _FakeBond(60)
    obj.update_intra_string_unhappiness()
    # 100 - round(60/3) = 80
    assert obj.intra_string_unhappiness == 80.0


def test_intra_unhappiness_middle_object_subtracts_sixth_of_total_strength():
    string = FakeString(length=3)
    obj = WorkspaceObject(string=string, left_pos=1, right_pos=1)  # middle
    obj.left_bond = _FakeBond(60)
    obj.right_bond = _FakeBond(60)
    obj.update_intra_string_unhappiness()
    # 100 - round(120/6) = 80
    assert obj.intra_string_unhappiness == 80.0


def test_intra_unhappiness_enclosed_object_uses_group_strength():
    string = FakeString(length=3)
    group = WorkspaceObject(string=string, left_pos=0, right_pos=1)
    group.strength = 70.0
    obj = WorkspaceObject(string=string, left_pos=1, right_pos=1)
    obj.enclosing_group = group
    obj.update_intra_string_unhappiness()
    assert obj.intra_string_unhappiness == 30.0  # 100 - 70


# ---- bridge weakness ------------------------------------------------------

def test_bridge_weakness_uses_bridge_strength():
    obj = WorkspaceObject(string=None, left_pos=0, right_pos=0)
    obj.horizontal_bridge = _FakeBridge(80)
    assert obj._bridge_weakness("horizontal") == 20.0  # 100 - 80


def test_bridge_weakness_full_when_no_bridge():
    obj = WorkspaceObject(string=None, left_pos=0, right_pos=0)
    assert obj._bridge_weakness("vertical") == 100.0


# ---- neighbour candidate sets  (Scheme: workspace-objects.ss:375-423) ------
#
# A bond candidate's neighbours are the adjacent *letter* — even when it sits
# inside a group — plus every group edged at that position, at any nesting level.
# The bond scouts used to filter to objects with the *identical*
# ``enclosing_group``, so a grouped letter was never a candidate for its ungrouped
# neighbour and whole classes of bond were unreachable.

def _string_with_rr_group():
    """``mrrjjj`` with the two ``r``s built into a group, as in §5.2.1 Run 1."""
    string = WorkspaceString("mrrjjj", _FakeSlipnet(), "initial")
    rr = Group(
        string=string,
        group_category=FakeNode("plato-same-group"),
        bond_facet=FakeNode("plato-letter-category"),
        direction=None,
        objects=[string.objects[1], string.objects[2]],
        bonds=[],
    )
    rr.proposal_level = Group.BUILT
    string.add_group(rr)
    return string, rr


def test_right_neighbours_include_the_letter_inside_an_adjacent_group():
    string, rr = _string_with_rr_group()
    m, first_r = string.objects[0], string.objects[1]
    assert string.text[1] == "r"
    assert set(map(id, m.get_all_right_neighbors())) == {id(first_r), id(rr)}


def test_m_can_be_chosen_as_a_bond_candidate_for_the_r_inside_the_group():
    """``m`` to the letter ``r`` inside ``[rr]`` — a bond Metacat can propose and
    Petacat could not reach at all."""
    string, rr = _string_with_rr_group()
    m, first_r = string.objects[0], string.objects[1]
    rng = RNG(0)
    chosen = {id(m.choose_neighbor(rng)) for _ in range(50)}
    assert id(first_r) in chosen


def test_directed_neighbour_choice_sees_both_levels():
    """The direction scout used ``get_object_at``, which returns the letter and
    never the group edged there (workspace-objects.ss:410-415)."""
    string, rr = _string_with_rr_group()
    m = string.objects[0]
    rng = RNG(0)
    chosen = {id(m.choose_right_neighbor(rng)) for _ in range(50)}
    assert chosen == {id(string.objects[1]), id(rr)}
    assert m.choose_left_neighbor(rng) is None


# ---------------------------------------------------------------------------
#  Which generator the neighbour pick draws from
# ---------------------------------------------------------------------------
#
# The pick is reached from the density walk of ``get-local-density``
# (bonds.ss:136-160, groups.ss:354-383), which runs on every strength update.
# It used to fall back to an RNG hung off the Workspace when the caller passed
# none, which under free-running meant the walk drew from the run's shared
# ``random.Random`` instead of from the executing codelet's own stream.


class _RecordingRNG:
    """Only the one method ``_pick_neighbor`` calls."""

    def __init__(self):
        self.picks = 0

    def weighted_pick(self, items, weights):
        self.picks += 1
        return items[0]


def test_the_neighbour_pick_draws_from_the_rng_it_is_given():
    string, rr = _string_with_rr_group()
    m = string.objects[0]
    rng = _RecordingRNG()

    assert m.choose_right_neighbor(rng) is string.objects[1]
    assert rng.picks == 1


def test_the_neighbour_pick_looks_for_no_generator_of_its_own():
    """With no RNG the walk stays defined and consults nothing.

    Specifically it does not go looking on the Workspace. Hanging the run's
    generator there was how the density walk got randomness before it was
    threaded from the call site, and it is the back-reference this pins closed:
    a caller with no RNG gets the first candidate, not a hidden shared one.
    """
    string, rr = _string_with_rr_group()
    m = string.objects[0]

    class _Workspace:
        def __getattr__(self, name):  # pragma: no cover - must never be reached
            raise AssertionError(f"the neighbour pick reached the Workspace for {name!r}")

    string.workspace = _Workspace()
    assert m.choose_right_neighbor(None) is string.objects[1]


def test_the_workspace_holds_no_generator_for_the_density_walk_to_find():
    from server.engine.workspace import Workspace

    workspace = Workspace("abc", "abd", "ijk", None, _FakeSlipnet())
    assert not hasattr(workspace, "rng")
