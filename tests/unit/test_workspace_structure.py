"""Tests for WorkspaceStructure base class with string proposal levels."""

from server.engine.workspace_structures import WorkspaceStructure


def test_proposal_levels_are_strings():
    """Proposal levels should be strings, not integers."""
    assert isinstance(WorkspaceStructure.PROPOSED, str)
    assert isinstance(WorkspaceStructure.EVALUATED, str)
    assert isinstance(WorkspaceStructure.BUILT, str)


def test_initial_proposal_level():
    s = WorkspaceStructure()
    assert s.proposal_level == "proposed"
    assert s.is_proposed
    assert not s.is_evaluated
    assert not s.is_built


def test_evaluate_sets_level():
    s = WorkspaceStructure()
    s.proposal_level = WorkspaceStructure.EVALUATED
    assert s.proposal_level == "evaluated"
    assert not s.is_proposed
    assert s.is_evaluated
    assert not s.is_built


def test_build_sets_level():
    s = WorkspaceStructure()
    s.proposal_level = WorkspaceStructure.BUILT
    assert s.proposal_level == "built"
    assert not s.is_proposed
    assert not s.is_evaluated
    assert s.is_built


def test_strength_defaults_to_zero():
    s = WorkspaceStructure()
    assert s.strength == 0.0


def test_weakness_inverse_of_strength():
    s = WorkspaceStructure()
    s.strength = 100.0
    # weakness = 100 - strength^0.95; at 100 it's about 20.6
    assert s.weakness() < 50.0
    s.strength = 0.0
    assert s.weakness() == 100.0


def test_unique_ids():
    s1 = WorkspaceStructure()
    s2 = WorkspaceStructure()
    assert s1.id != s2.id


def test_repr_contains_level_string():
    s = WorkspaceStructure()
    r = repr(s)
    assert "proposed" in r
    s.proposal_level = WorkspaceStructure.BUILT
    r = repr(s)
    assert "built" in r
