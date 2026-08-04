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


# --- fully-active? vs above-threshold?  (slipnet.ss:392-404) ----------------
#
# Two predicates, two thresholds.  ``fully-active?`` is exact equality with
# %max-activation%; ``above-threshold?`` is >= %full-activation-threshold%, and
# its only consumer in the reference is top-down codelet posting
# (slipnet.ss:212-213).  Everything downstream of the first — link shrinking,
# degrees of association, concept-mapping and description relevance — treats the
# whole 50-99 band as *not* saturated.


def _node_at(activation: float, *, intrinsic_link_length: int = 60) -> SlipnetNode:
    node = SlipnetNode("label", "label", 50)
    node.intrinsic_link_length = intrinsic_link_length
    node.activation = activation
    return node


def test_fully_active_is_false_just_below_the_ceiling():
    assert _node_at(99.0).fully_active() is False


def test_fully_active_is_true_only_at_the_ceiling():
    assert _node_at(100.0).fully_active() is True


def test_above_threshold_is_false_at_49():
    assert _node_at(49.0).above_threshold() is False


def test_above_threshold_is_true_from_50_up():
    assert _node_at(50.0).above_threshold() is True
    assert _node_at(99.0).above_threshold() is True
    assert _node_at(100.0).above_threshold() is True


def test_degree_of_assoc_uses_the_intrinsic_length_below_the_ceiling():
    """49, 50 and 99 all give 100 - 60 = 40: nothing shrinks before saturation."""
    assert _node_at(49.0).degree_of_assoc() == 40.0
    assert _node_at(50.0).degree_of_assoc() == 40.0
    assert _node_at(99.0).degree_of_assoc() == 40.0


def test_degree_of_assoc_shrinks_only_at_full_activation():
    """At 100 the shrunk length applies: 40% of 60 = 24, so 100 - 24 = 76."""
    assert _node_at(100.0).degree_of_assoc() == 76.0


# --- the probabilistic jump's candidate window (slipnet.ss:387-389) ---------


def test_partially_active_is_the_half_open_interval_50_to_100():
    assert _node_at(49.0).partially_active() is False
    assert _node_at(50.0).partially_active() is True
    assert _node_at(99.0).partially_active() is True
    assert _node_at(100.0).partially_active() is False


def test_a_node_below_the_threshold_never_jumps():
    """(30/100)^3 = 0.027 — small, but the reference does not draw at all.

    Left unfiltered, a residual activation would keep a finished concept
    flickering back to saturation for the rest of the run.
    """
    rng = RNG(7)
    for _ in range(20_000):
        node = _node_at(30.0)
        node.probabilistic_jump_to_full(rng)
        assert node.activation == 30.0
    assert rng.call_count == 0, "a node below the threshold must not consume a draw"


def test_a_partially_active_node_jumps_at_the_cube_of_its_activation():
    """60 => (0.6)^3 = 0.216, within sampling error over 20,000 trials."""
    rng = RNG(11)
    trials = 20_000
    jumps = 0
    for _ in range(trials):
        node = _node_at(60.0)
        node.probabilistic_jump_to_full(rng)
        if node.activation == 100.0:
            jumps += 1
    observed = jumps / trials
    # sigma = sqrt(0.216 * 0.784 / 20000) = 0.0029; 0.01 is ~3.4 sigma.
    assert abs(observed - 0.216) < 0.01, f"observed {observed:.4f}, expected 0.216"
    assert rng.call_count == trials, "every partially-active node consumes one draw"


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


def test_dynamic_degree_does_not_shrink_for_a_label_at_99():
    """A link shrinks on ``fully-active?``, not on ``above-threshold?``.

    Scheme: ``get-degree-of-assoc`` on a link (slipnet.ss:334-339).  At 99 the
    label is well past the threshold and the link is still its full intrinsic
    length, so the association stays 40 rather than jumping to 76 — a difference
    that a bond's strength (``11·√assoc``) turns into 70 against 96.
    """
    link = _labeled_lateral_link()
    link.label_node.activation = 99.0
    assert link.degree_of_association() == 40.0


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
