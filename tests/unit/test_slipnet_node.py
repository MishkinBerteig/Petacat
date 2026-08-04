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


# --- decay is integer arithmetic, and deep concepts plateau ----------------
#
# ``decay-activation`` (slipnet.ss:174-177) is
# ``(round (* rate-of-decay activation))`` over exact rationals, so the amount
# lost is a whole number and a deep node reaches a fixed point instead of
# tending to zero.  Decaying in floats loses that: the plateaus are what keeps a
# concept the program has used quietly present in the network afterwards.


def _decayed(depth: int, start: float, cycles: int) -> float:
    """*start*, decayed *cycles* times by a node of conceptual depth *depth*."""
    node = SlipnetNode("n", "n", depth)
    node.compute_rate_of_decay(15)
    node.activation = start
    for _ in range(cycles):
        node.decay()
        node.activation = max(0.0, min(100.0, node.activation + node.activation_buffer))
        node.activation_buffer = 0.0
    return node.activation


def test_a_depth_90_node_plateaus_at_5_instead_of_decaying_away():
    """Rate 1/10, so at 5 the amount is ``round(0.5)`` — 0 under round-half-even.

    Both Scheme's ``round`` and Python's break the tie to even, and 0 is even, so
    the node stops losing activation entirely.  It is *not* a slow approach to
    zero: run it a thousand more cycles and it is still 5.
    """
    assert _decayed(90, 100.0, cycles=200) == 5.0
    assert _decayed(90, 100.0, cycles=1200) == 5.0
    assert _decayed(90, 5.0, cycles=1) == 5.0


def test_a_depth_80_node_sticks_at_2():
    """Rate 1/5: ``round(0.4) = 0`` at 2, while 3 still loses 1 (``round(0.6)``)."""
    assert _decayed(80, 100.0, cycles=200) == 2.0
    assert _decayed(80, 3.0, cycles=1) == 2.0
    assert _decayed(80, 2.0, cycles=1) == 2.0


def test_a_shallow_node_has_no_plateau_and_reaches_zero():
    """At depth 10 the rate is 9/10; no activation below 1 survives rounding."""
    assert _decayed(10, 100.0, cycles=20) == 0.0


def test_the_plateau_is_the_largest_fixed_point_of_the_rounded_rate():
    """One table, stating the whole shape of it for the nine depths in the seed data.

    Read it as: a node this deep, left alone, ends here.  The value is the
    largest ``a`` with ``round((100 - depth)/100 · a) == 0``.
    """
    assert {d: _decayed(d, 100.0, cycles=400) for d in range(10, 100, 10)} == {
        10: 0.0, 20: 0.0, 30: 0.0, 40: 0.0,
        50: 1.0, 60: 1.0, 70: 1.0, 80: 2.0, 90: 5.0,
    }


def test_decay_leaves_the_activation_an_integer():
    """The amount is rounded, so an integral activation stays integral.

    Every other write to a slipnode's activation in the reference is an integer
    too — the Workspace jolt is 100 (slipnet.ss:171-172), a spread contribution
    is rounded (slipnet.ss:183-185), a clamp and a jump write 100 — so this is
    what keeps the whole network on the integers, and the plateaus reachable.
    """
    for depth in range(10, 100, 10):
        node = SlipnetNode("n", "n", depth)
        node.compute_rate_of_decay(15)
        node.activation = 97.0
        for _ in range(40):
            node.decay()
            assert node.activation_buffer == int(node.activation_buffer)
            node.activation += node.activation_buffer
            node.activation_buffer = 0.0
            assert node.activation == int(node.activation), (
                f"depth {depth} left activation at {node.activation!r}"
            )


def test_a_frozen_node_does_not_decay():
    """slipnet.ss:174-177 decrements through the buffer, which a frozen node refuses."""
    node = SlipnetNode("n", "n", 10)
    node.compute_rate_of_decay(15)
    node.activation = 100.0
    node.frozen = True
    node.decay()
    assert node.activation_buffer == 0.0


def test_the_decay_rate_is_exact_at_the_shipped_update_cycle_length():
    """``100 - depth``, not ``100 * (1 - depth/100)``.

    The distinction is the whole fix: ``1 - 90/100`` is 0.09999999999999998 in
    float64, whose product with an activation of 15 is 1.4999999999999998 and
    rounds *down* where the reference rounds up.  Holding the percentage as a
    small exact integer makes the product exact and the halfway cases exactly
    representable — in float32 as well, which is what lets the Metal backend
    round identically.
    """
    node = SlipnetNode("n", "n", 90)
    node.compute_rate_of_decay(15)
    assert node._decay_percent == 10.0
    node.activation = 15.0
    node.decay()
    assert node.activation_buffer == -2.0  # round(1.5) == 2, not 1


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


# --- get-similar-property-links  (slipnet.ss:108-112) ----------------------
#
# A property link is followed *stochastically*, with probability equal to its
# degree of association:
#
#     (filter (lambda (link)
#               (prob? (temp-adjusted-probability
#                        (% (tell link 'get-degree-of-assoc)))))
#       property-links)
#
# Following every property link unconditionally, as Petacat's bottom-up
# description scout used to, makes the `first`/`last` descriptions that drive the
# xyz family's opposite mappings several times as common as the reference makes
# them — and makes them at a rate no longer sensitive to temperature.


class _ScriptedRNG:
    """Answers ``prob`` from a script and records what it was asked."""

    def __init__(self, answers):
        self._answers = list(answers)
        self.asked = []

    def prob(self, p):
        self.asked.append(p)
        return self._answers.pop(0)


def _node_with_property_links(*lengths):
    node = SlipnetNode("a", "a", 10)
    for i, length in enumerate(lengths):
        target = SlipnetNode(f"prop{i}", f"prop{i}", 10)
        node.property_links.append(
            SlipnetLink(node, target, "property", fixed_link_length=length)
        )
    return node


def test_similar_property_links_asks_for_the_links_degree_of_association():
    node = _node_with_property_links(75)
    rng = _ScriptedRNG([True])
    node.get_similar_property_links(rng)
    # a→alphabetic-first is length 75, so association 25.
    assert rng.asked == [0.25]


def test_similar_property_links_keeps_only_the_links_that_win_their_draw():
    node = _node_with_property_links(75, 10)
    rng = _ScriptedRNG([False, True])
    kept = node.get_similar_property_links(rng)
    assert kept == [node.property_links[1]]


def test_similar_property_links_can_come_back_empty():
    """An empty result is a fizzle, not a fallback (descriptions.ss:115-117)."""
    node = _node_with_property_links(75)
    assert node.get_similar_property_links(_ScriptedRNG([False])) == []


def test_a_node_without_property_links_asks_nothing():
    node = SlipnetNode("b", "b", 10)
    rng = _ScriptedRNG([])
    assert node.get_similar_property_links(rng) == []
    assert rng.asked == []


# --- a frozen node takes nothing in  (slipnet.ss:139-145, 157-163) ---------


def test_a_frozen_node_receives_no_spreading():
    """``increment-activation-buffer`` (``slipnet.ss:157-160``) refuses while the node
    is frozen, which is what makes a clamp hold a value rather than merely start it
    there.

    Live for any concept pinned *below* 100 — a negative theme clamps
    ``plato-opposite`` to zero (``trace.ss:1512-1514``) — where buffering the spread in
    let the concept climb back on the next flush.
    """
    source = SlipnetNode("source", "source", 50)
    target = SlipnetNode("target", "target", 50)
    source.lateral_links.append(
        SlipnetLink(source, target, "lateral", fixed_link_length=0)
    )
    source.activation = 100.0
    target.clamp(0, activation=0.0)

    source.spread_activation_to_neighbors(15)

    assert target.activation_buffer == 0.0


def test_an_unfrozen_node_does_receive_spreading():
    source = SlipnetNode("source", "source", 50)
    target = SlipnetNode("target", "target", 50)
    source.lateral_links.append(
        SlipnetLink(source, target, "lateral", fixed_link_length=0)
    )
    source.activation = 100.0

    source.spread_activation_to_neighbors(15)

    assert target.activation_buffer == 100.0


def test_clamping_discards_whatever_the_node_was_about_to_receive():
    """``slipnet.ss:142`` sets ``activation-buffer`` to 0 inside ``clamp``.

    Left in place, a jolt a codelet delivered just before the clamp was added on top of
    the clamped value at the next flush.
    """
    node = SlipnetNode("n", "n", 50)
    node.activate_from_workspace()
    assert node.activation_buffer == 100.0

    node.clamp(0, activation=0.0)

    assert node.activation_buffer == 0.0
    assert node.activation == 0.0
