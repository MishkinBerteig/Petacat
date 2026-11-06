"""Tests for WorkspaceStructure base class with string proposal levels."""

from server.engine.workspace_structures import WorkspaceStructure
from tests.support import standard_names


class _Structure(WorkspaceStructure):
    """The base class declares ``__slots__`` (the built level's name); every real structure is a
    subclass without them and so has a ``__dict__``, which is what these tests need."""


def test_proposal_levels_are_strings():
    """Proposal levels should be strings, not integers: the run's vocabulary names."""
    s = _Structure()
    assert isinstance(s.proposal_level, str)
    assert isinstance(s._built_level, str)
    assert isinstance(standard_names.EVALUATED, str)


def test_initial_proposal_level():
    s = _Structure()
    assert s.proposal_level == "proposed"
    assert not s.is_built


def test_evaluate_sets_level():
    s = _Structure()
    s.proposal_level = standard_names.EVALUATED
    assert s.proposal_level == "evaluated"
    assert not s.is_built


def test_build_sets_level():
    s = _Structure()
    s.proposal_level = standard_names.BUILT
    assert s.proposal_level == "built"
    assert s.is_built


def test_strength_defaults_to_zero():
    s = _Structure()
    assert s.strength == 0.0


def test_weakness_is_low_at_full_strength():
    s = _Structure()
    s.strength = 100.0
    # weakness = 100 - strength^0.95; at 100 it's about 20.6
    assert s.weakness() < 50.0


def test_weakness_is_maximal_at_zero_strength():
    s = _Structure()
    s.strength = 0.0
    assert s.weakness() == 100.0


def test_unique_ids():
    s1 = _Structure()
    s2 = _Structure()
    assert s1.id != s2.id


def test_repr_contains_proposed_level_string():
    s = _Structure()
    assert "proposed" in repr(s)


def test_repr_contains_built_level_string():
    s = _Structure()
    s.proposal_level = standard_names.BUILT
    assert "built" in repr(s)
