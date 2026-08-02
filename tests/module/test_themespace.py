"""Module integration tests for Themespace."""

import os
import pytest
from server.engine.metadata import MetadataProvider
from server.engine.themes import Themespace, THEME_TOP_BRIDGE, THEME_BOTTOM_BRIDGE, THEME_VERTICAL_BRIDGE

# Every test here executes arithmetic the numeric substrate owns, so each one runs
# once per backend in the matrix. See tests/conftest.py.
pytestmark = pytest.mark.numeric_matrix


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


def test_possible_types_default(themespace):
    assert THEME_TOP_BRIDGE in themespace.possible_theme_types
    assert THEME_VERTICAL_BRIDGE in themespace.possible_theme_types
    assert THEME_BOTTOM_BRIDGE not in themespace.possible_theme_types


def test_thematic_pressure_is_off_by_default(themespace):
    """§4.1.2: themes are passive most of the time.

    Scheme: ``active-theme-types`` starts as '() (themes.ss:53).
    """
    assert themespace.active_theme_types == []


def test_justify_mode_makes_bottom_themes_possible(themespace):
    themespace.set_justify_mode(True)
    assert THEME_BOTTOM_BRIDGE in themespace.possible_theme_types


def test_pressure_only_covers_possible_types(themespace):
    themespace.thematic_pressure_on()
    assert set(themespace.active_theme_types) == {
        THEME_TOP_BRIDGE,
        THEME_VERTICAL_BRIDGE,
    }
    themespace.thematic_pressure_off()
    assert themespace.active_theme_types == []


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


def test_a_negative_theme_decays_toward_zero(themespace, meta):
    """A negative theme becomes less negative over time.

    ``activation-function`` (``themes.ss:456-459``) subtracts the net effect for a
    negatively-activated theme, so the decay term — which makes the net effect
    negative — moves the activation toward zero, which is where a theme that nothing
    is reinforcing ends up whichever pole it sits on.
    """
    cluster = themespace.clusters[0]
    theme = cluster.themes[0]
    theme.clamp(-80.0)
    theme.unclamp()  # Frozen=False but activation stays at -80

    assert theme.activation == -80.0

    cluster.spread_activation(meta)

    assert -80.0 < theme.activation <= 0.0


def test_theme_to_slipnet_spreading(themespace, meta):
    """Themes spread to the Slipnet only while thematic pressure is on.

    §4.1.2: "whenever thematic pressure is turned on, themes spread activation
    to their constituent Slipnet concepts".
    """
    themespace.thematic_pressure_on()
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


# --- displaying a past episode over the live Themespace ---------------------
#
# Every MetaCat event and every stored answer answers `display`: it saves the live
# Themespace, clears it, and imposes that episode's own theme-pattern
# (trace.ss:415-420, trace.ss:809, memory.ss:275-277).  Clicking again restores what
# the program was actually thinking.  Without the save/restore half, inspecting the
# past would silently overwrite the present.


def _clusters_of(themespace, theme_type):
    return [c for c in themespace.clusters if c.theme_type == theme_type]


def test_saving_and_restoring_returns_every_theme_to_where_it_was(meta):
    from server.engine.themes import Themespace

    themespace = Themespace(meta)
    cluster = _clusters_of(themespace, "vertical_bridge")[0]
    live = cluster.themes[0]
    live.activation = 64.0
    cluster.frozen = True
    themespace.thematic_pressure_on(["vertical_bridge"])

    themespace.save_current_state()
    assert themespace.displaying_past_state

    # Whatever the display does to the Themespace...
    for theme in cluster.themes:
        theme.activation = 0.0
    cluster.frozen = False
    themespace.thematic_pressure_off(["vertical_bridge"])

    assert themespace.restore_current_state()
    assert live.activation == 64.0
    assert cluster.frozen is True
    assert "vertical_bridge" in themespace.active_theme_types
    assert not themespace.displaying_past_state


def test_restoring_without_a_saved_state_reports_that_it_did_nothing(meta):
    """So a caller cannot mistake "nothing to restore" for a successful restore."""
    from server.engine.themes import Themespace

    assert Themespace(meta).restore_current_state() is False
