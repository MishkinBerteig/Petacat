"""The Slipnet built from ``seed_data/`` — its nodes, its links and its dynamics."""

import os
import pytest
from server.engine.slipnet import Slipnet
from server.engine.metadata import MetadataProvider


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


def test_clamp_freezes_node_at_full_activation(slipnet):
    node = slipnet.get_node("plato-a")
    node.clamp(5)
    assert node.frozen
    assert node.activation == 100.0
    assert node.clamp_cycles_remaining == 5


def test_clamp_expires_after_its_cycles(slipnet):
    node = slipnet.get_node("plato-a")
    node.clamp(5)
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


def test_reset_clears_node_activation(slipnet):
    slipnet.get_node("plato-a").activation = 50
    slipnet.reset_activations()
    assert slipnet.get_node("plato-a").activation == 0


def test_reset_releases_clamped_node(slipnet):
    slipnet.get_node("plato-b").clamp(10)
    slipnet.reset_activations()
    assert not slipnet.get_node("plato-b").frozen


def test_partially_active_node_does_not_spread_at_high_threshold(slipnet):
    """A node at 50 activation must not spread when the threshold is 100."""
    succ = slipnet.get_node("plato-successor")
    succ.activation = 50.0
    bc = slipnet.get_node("plato-bond-category")
    bc.activation = 0.0
    slipnet.spread_activation(15, threshold=100)
    # succ is below threshold, so bond-category receives no spread from it.
    assert bc.activation == 0.0


def test_partially_active_node_spreads_at_zero_threshold(slipnet):
    """The same node at 50 activation spreads once the threshold drops to 0."""
    succ = slipnet.get_node("plato-successor")
    succ.activation = 50.0
    bc = slipnet.get_node("plato-bond-category")
    bc.activation = 0.0
    slipnet.spread_activation(15, threshold=0)
    assert bc.activation > 0.0
