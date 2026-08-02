"""Slipnet nodes and links built directly, with no network around them.

A node and a link are enough to state what a degree of association is and when a
probabilistic jump fires.  The same classes read from ``seed_data/`` are exercised
in ``tests/seed_unit/test_slipnet_node.py``.
"""

from server.engine.rng import RNG
from server.engine.slipnet import SlipnetLink, SlipnetNode


def test_degree_of_association():
    n1 = SlipnetNode("n1", "n1", 50)
    n2 = SlipnetNode("n2", "n2", 50)
    link = SlipnetLink(n1, n2, "lateral", fixed_link_length=30)
    assert link.degree_of_association() == 70.0


def test_probabilistic_jump():
    node = SlipnetNode("test", "test", 50)
    node.activation = 99.0  # Very high activation => very likely to jump
    rng = RNG(42)
    node.probabilistic_jump_to_full(rng)
    assert node.activation == 100.0


def _labeled_lateral_link():
    """A lateral link whose label is fully active (so dynamic length shrinks)."""
    label = SlipnetNode("label", "label", 50)
    label.intrinsic_link_length = 60
    label.activation = 100.0  # Fully active
    n1 = SlipnetNode("n1", "n1", 50)
    n2 = SlipnetNode("n2", "n2", 50)
    return SlipnetLink(n1, n2, "lateral", label_node=label)


def test_intrinsic_degree_ignores_shrunk_length_when_label_active():
    link = _labeled_lateral_link()
    # Intrinsic always uses the full intrinsic length: 100 - 60 = 40.
    assert link.intrinsic_degree_of_association() == 40.0


def test_dynamic_degree_uses_shrunk_length_when_label_active():
    link = _labeled_lateral_link()
    # Dynamic uses shrunk length (40% of 60 = 24), so 100 - 24 = 76.
    assert link.degree_of_association() == 76.0


def test_fixed_link_intrinsic_degree_is_100_minus_length():
    n1 = SlipnetNode("n1", "n1", 50)
    n2 = SlipnetNode("n2", "n2", 50)
    link = SlipnetLink(n1, n2, "lateral", fixed_link_length=30)
    assert link.intrinsic_degree_of_association() == 70.0


def test_fixed_link_intrinsic_and_dynamic_degrees_match():
    n1 = SlipnetNode("n1", "n1", 50)
    n2 = SlipnetNode("n2", "n2", 50)
    link = SlipnetLink(n1, n2, "lateral", fixed_link_length=30)
    # A fixed-length link has no label, so shrinking never applies.
    assert link.intrinsic_degree_of_association() == link.degree_of_association()
