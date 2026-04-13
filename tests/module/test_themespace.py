"""Module integration tests for Themespace."""

import os
import pytest
from server.engine.metadata import MetadataProvider
from server.engine.themes import Themespace, THEME_TOP_BRIDGE, THEME_BOTTOM_BRIDGE, THEME_VERTICAL_BRIDGE


SEED_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "seed_data")


@pytest.fixture
def meta():
    return MetadataProvider.from_seed_data(SEED_DIR)


@pytest.fixture
def themespace(meta):
    return Themespace(meta)


def test_cluster_count(themespace):
    # 9 dimensions * 3 theme types = 27 clusters
    assert len(themespace.clusters) == 27


def test_active_types_default(themespace):
    assert THEME_TOP_BRIDGE in themespace.active_theme_types
    assert THEME_VERTICAL_BRIDGE in themespace.active_theme_types
    assert THEME_BOTTOM_BRIDGE not in themespace.active_theme_types


def test_justify_mode_activates_bottom(themespace):
    themespace.set_justify_mode(True)
    assert THEME_BOTTOM_BRIDGE in themespace.active_theme_types


def test_boost_theme(themespace):
    themespace.boost_theme(
        THEME_TOP_BRIDGE,
        "plato-direction-category",
        "identity",
        100.0,
    )
    for cluster in themespace.clusters:
        if (cluster.theme_type == THEME_TOP_BRIDGE
                and cluster.dimension == "plato-direction-category"):
            theme = cluster.get_theme("identity")
            assert theme is not None
            assert theme.activation > 0
            break


def test_no_pressure_initially(themespace):
    assert not themespace.has_thematic_pressure()


def test_spread_activation_runs(themespace):
    """Spreading should not crash even with no activation."""
    themespace.spread_activation()


def test_reset(themespace):
    themespace.boost_theme(THEME_TOP_BRIDGE, "plato-direction-category", "identity", 100)
    themespace.reset()
    assert themespace.get_max_positive_theme_activation() == 0


def test_current_pattern(themespace):
    pattern = themespace.get_current_pattern()
    assert "top_bridge" in pattern
    assert "vertical_bridge" in pattern


def test_negative_activation_decays_toward_zero(themespace, meta):
    """Negative themes should decay toward 0 over time (become less negative).

    The negative_activation update uses `- net_effect` so that the decay
    term (which produces a negative net_effect) pushes negative activation
    toward 0 rather than further from it.
    """
    cluster = themespace.clusters[0]
    theme = cluster.themes[0]
    theme.clamp(-80.0)
    theme.unclamp()  # Frozen=False but activation stays at -80

    initial_neg = theme.negative_activation
    assert initial_neg == -80.0

    # After spreading, decay should push negative activation toward 0
    cluster.spread_activation(meta)

    # Should become less negative (closer to 0)
    assert theme.negative_activation > initial_neg


def test_theme_to_slipnet_spreading(themespace, meta):
    """Active themes should stochastically activate slipnet nodes."""
    from server.engine.slipnet import Slipnet
    from server.engine.rng import RNG

    slipnet = Slipnet.from_metadata(meta)
    rng = RNG(42)

    # Boost a theme to high activation
    themespace.boost_theme(
        THEME_TOP_BRIDGE,
        "plato-direction-category",
        "identity",
        100.0,
    )
    # Boost repeatedly to get to high activation
    for _ in range(20):
        themespace.boost_theme(
            THEME_TOP_BRIDGE,
            "plato-direction-category",
            "identity",
            100.0,
        )

    # Clear slipnet buffers
    for node in slipnet.nodes.values():
        node.activation_buffer = 0.0

    # Spread theme activation to slipnet
    themespace.spread_activation_to_slipnet(slipnet, rng)

    # The dimension node (plato-direction-category) should have buffer > 0
    dir_node = slipnet.nodes["plato-direction-category"]
    # With high theme activation, probability is high but still stochastic
    # Run multiple times to be confident
    total_buffer = 0.0
    for _ in range(20):
        for node in slipnet.nodes.values():
            node.activation_buffer = 0.0
        themespace.spread_activation_to_slipnet(slipnet, rng)
        total_buffer += dir_node.activation_buffer

    assert total_buffer > 0, "Theme→slipnet spreading should activate dimension nodes"
