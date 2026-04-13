"""Tests for Slipnet nodes and links."""

import os
import pytest
from server.engine.slipnet import Slipnet, SlipnetNode, SlipnetLink
from server.engine.metadata import MetadataProvider
from server.engine.rng import RNG


SEED_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "seed_data")


@pytest.fixture
def meta():
    return MetadataProvider.from_seed_data(SEED_DIR)


@pytest.fixture
def slipnet(meta):
    return Slipnet.from_metadata(meta)


def test_slipnet_node_count(slipnet):
    assert len(slipnet.nodes) == 59


def test_node_properties(slipnet):
    node = slipnet.get_node("plato-a")
    assert node.short_name == "a"
    assert node.conceptual_depth == 10
    assert node.activation == 0.0


def test_successor_has_intrinsic_link_length(slipnet):
    succ = slipnet.get_node("plato-successor")
    assert succ.intrinsic_link_length == 60


def test_identity_has_intrinsic_link_length(slipnet):
    identity = slipnet.get_node("plato-identity")
    assert identity.intrinsic_link_length == 0


def test_node_links_populated(slipnet):
    """Letters should have category links to letter-category."""
    a = slipnet.get_node("plato-a")
    cat_links = a.category_links
    assert len(cat_links) > 0
    assert any(lk.to_node.name == "plato-letter-category" for lk in cat_links)


def test_letter_successor_links(slipnet):
    """plato-a should have a lateral successor link to plato-b."""
    a = slipnet.get_node("plato-a")
    succ_links = [
        lk for lk in a.lateral_links
        if lk.to_node.name == "plato-b" and lk.label_node and lk.label_node.name == "plato-successor"
    ]
    assert len(succ_links) == 1


def test_opposite_sliplinks(slipnet):
    """leftmost should have a lateral-sliplink to rightmost labeled opposite."""
    lm = slipnet.get_node("plato-leftmost")
    opp_links = [
        lk for lk in lm.lateral_sliplinks
        if lk.to_node.name == "plato-rightmost"
    ]
    assert len(opp_links) == 1
    assert opp_links[0].label_node.name == "plato-opposite"


def test_clamp_and_unclamp(slipnet):
    node = slipnet.get_node("plato-a")
    node.clamp(5)
    assert node.frozen
    assert node.activation == 100.0
    assert node.clamp_cycles_remaining == 5

    for _ in range(5):
        node.tick_clamp()
    assert not node.frozen
    assert node.clamp_cycles_remaining == 0


def test_spread_activation(slipnet):
    """Activating a node should spread some activation to neighbors."""
    succ = slipnet.get_node("plato-successor")
    succ.activation = 100.0
    slipnet.spread_activation(15)
    # Bond-category should get some activation (succ has category link to it)
    bc = slipnet.get_node("plato-bond-category")
    assert bc.activation > 0


def test_clamp_initially_relevant(slipnet, meta):
    slipnet.clamp_initially_relevant(meta)
    lc = slipnet.get_node("plato-letter-category")
    sp = slipnet.get_node("plato-string-position-category")
    assert lc.frozen
    assert sp.frozen
    assert lc.activation == 100.0


def test_reset(slipnet):
    slipnet.get_node("plato-a").activation = 50
    slipnet.get_node("plato-b").clamp(10)
    slipnet.reset_activations()
    assert slipnet.get_node("plato-a").activation == 0
    assert not slipnet.get_node("plato-b").frozen


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


def test_intrinsic_degree_of_association():
    """Intrinsic degree should NOT use shrunk length, even when label is active."""
    label = SlipnetNode("label", "label", 50)
    label.intrinsic_link_length = 60
    label.activation = 100.0  # Fully active

    n1 = SlipnetNode("n1", "n1", 50)
    n2 = SlipnetNode("n2", "n2", 50)
    link = SlipnetLink(n1, n2, "lateral", label_node=label)

    # Intrinsic: 100 - 60 = 40 (always uses intrinsic length)
    assert link.intrinsic_degree_of_association() == 40.0

    # Dynamic: should use shrunk (40% of 60 = 24), so 100 - 24 = 76
    assert link.degree_of_association() == 76.0

    # They should differ when label is fully active
    assert link.intrinsic_degree_of_association() != link.degree_of_association()


def test_spreading_respects_threshold(slipnet):
    """Only nodes at or above threshold should spread activation."""
    # Set up: plato-successor at 50 activation (below 100 threshold)
    succ = slipnet.get_node("plato-successor")
    succ.activation = 50.0

    # With default threshold=100, a node at 50 should NOT spread
    bc = slipnet.get_node("plato-bond-category")
    bc.activation = 0.0
    slipnet.spread_activation(15, threshold=100)

    # bond-category should NOT get activation from succ (below threshold)
    # (it may get small activation from decay buffer effects, but succ shouldn't spread)
    bc_act_high_threshold = bc.activation

    # Reset and try with threshold=0
    slipnet.reset_activations()
    succ.activation = 50.0
    slipnet.spread_activation(15, threshold=0)
    bc_act_low_threshold = bc.activation

    # With threshold=0, succ at 50 should have spread, giving bond-category more
    assert bc_act_low_threshold > bc_act_high_threshold


def test_fixed_link_intrinsic_degree():
    """Fixed-length links should return correct intrinsic degree."""
    n1 = SlipnetNode("n1", "n1", 50)
    n2 = SlipnetNode("n2", "n2", 50)
    link = SlipnetLink(n1, n2, "lateral", fixed_link_length=30)
    assert link.intrinsic_degree_of_association() == 70.0
    # Same as dynamic for fixed-length links
    assert link.intrinsic_degree_of_association() == link.degree_of_association()
