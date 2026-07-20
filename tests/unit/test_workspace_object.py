"""Tests for WorkspaceObject and Letter.

The first three tests exercise construction and the legacy salience shim; the
rest isolate one path each through the object's geometry, bond bookkeeping,
importance, unhappiness, and bridge-weakness logic. Collaborators (string,
bonds, bridges, descriptions) are lightweight fakes so no path depends on the
full engine or the database. No randomness is involved.
"""

from server.engine.workspace_objects import Letter, WorkspaceObject
from server.engine.slipnet import SlipnetNode

from tests.unit._fakes import FakeNode, FakeString


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
