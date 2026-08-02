"""Unit tests for engine.themes (Themespace self-watching dynamics).

The Themespace is MetaCat's central innovation over Copycat. These tests
isolate:
  * Theme  — boost / clamp arithmetic and sign predicates (pure).
  * ThemeCluster — dominant-theme selection branches and intra-cluster
    spreading (config fully mocked by FakeMeta so the tanh dynamics are
    deterministic and exactly assertable).
  * Themespace — thematic pressure, boosting, negative clamping, justify mode.

No RNG is used (the one stochastic method, spread_activation_to_slipnet, is
covered elsewhere); determinism is by construction.
"""

import math

from server.engine.themes import (
    THEME_BOTTOM_BRIDGE,
    THEME_TOP_BRIDGE,
    THEME_VERTICAL_BRIDGE,
    Theme,
    ThemeCluster,
    Themespace,
)


# --- config test double ----------------------------------------------------

class _FakeDim:
    def __init__(self, slipnet_node, valid_relations):
        self.slipnet_node = slipnet_node
        self.valid_relations = valid_relations


class _FakeMeta:
    """Fully mocks MetadataProvider for the subset the Themespace reads."""

    def __init__(self, dims, params=None, coeffs=None):
        self.theme_dimensions = dims
        self._params = params or {}
        self._coeffs = coeffs or {}

    def get_param(self, name, default=None):
        return self._params.get(name, default)

    def get_formula_coeff(self, name):
        return self._coeffs[name]


# Coefficients making intra-cluster spreading deterministic.
_SPREAD_COEFFS = {
    "theme_intra_cluster_neg_to_neg_weight": 0.0,
    "theme_intra_cluster_neg_to_pos_weight": 0.0,
    "theme_intra_cluster_pos_to_neg_weight": 0.0,
    "theme_intra_cluster_pos_to_pos_weight": 0.0,
    "theme_intra_cluster_self_weight": 50.0,
    "theme_net_effect_default_sensitivity": 1.0,
}
_SPREAD_PARAMS = {"theme_decay_amount": 25, "theme_spread_amount": 20}


# --- Theme: sign predicates ------------------------------------------------

def test_theme_is_positive_when_activation_above_zero():
    t = Theme(THEME_TOP_BRIDGE, "direction", "identity")
    t.activation = 30.0
    assert t.is_positive is True


def test_theme_is_negative_when_activation_below_zero():
    t = Theme(THEME_TOP_BRIDGE, "direction", "identity")
    t.activation = -30.0
    assert t.is_negative is True


# --- Theme: boost ----------------------------------------------------------

def test_boost_raises_activation():
    t = Theme(THEME_TOP_BRIDGE, "direction", "identity")
    t.boost(factor=100.0, boost_amount=7.0)  # round(0 + 1.0 * 7) = 7
    assert t.activation == 7.0


def test_boost_caps_activation_at_100():
    t = Theme(THEME_TOP_BRIDGE, "direction", "identity")
    t.activation = 98.0
    t.boost(factor=100.0, boost_amount=7.0)  # 98 + 7 -> capped 100
    assert t.activation == 100.0


def test_boost_clips_at_zero_rather_than_going_negative():
    """``themes.ss:674-679`` applies ``clip-positive`` to the whole boost.

    A boost carries the Workspace's push toward a theme's positive pole, so it can
    take a theme up to +100 and can take a negative theme up to zero, and stops there.
    """
    t = Theme(THEME_TOP_BRIDGE, "direction", "identity")
    t.boost(factor=-100.0, boost_amount=7.0)
    assert t.activation == 0.0


def test_boost_moves_a_negative_theme_toward_zero():
    """One signed activation: boosting a theme at -50 gives ``clip_positive(-43)``."""
    t = Theme(THEME_TOP_BRIDGE, "direction", "identity")
    t.activation = -50.0
    t.boost(factor=100.0, boost_amount=7.0)
    assert t.activation == 0.0


# --- Theme: clamp ----------------------------------------------------------

def test_clamp_negative_value_freezes_and_sets_a_negative_activation():
    t = Theme(THEME_TOP_BRIDGE, "direction", "identity")
    t.clamp(-100.0)
    assert t.frozen is True
    assert t.activation == -100.0


def test_clamp_positive_value_sets_a_positive_activation():
    t = Theme(THEME_TOP_BRIDGE, "direction", "identity")
    t.clamp(60.0)
    assert t.activation == 60.0


# --- ThemeCluster: dominant theme ------------------------------------------

def _cluster(relations=("identity", "opposite")):
    return ThemeCluster(THEME_TOP_BRIDGE, "direction", list(relations))


def test_no_dominant_theme_when_none_positive():
    cluster = _cluster()
    for t in cluster.themes:
        t.activation = 0.0
    assert cluster.get_dominant_theme(margin=90.0) is None


def test_single_positive_theme_is_dominant_when_it_meets_margin():
    cluster = _cluster()
    cluster.themes[0].activation = 95.0
    cluster.themes[1].activation = 0.0
    assert cluster.get_dominant_theme(margin=90.0) is cluster.themes[0]


def test_single_positive_theme_not_dominant_below_margin():
    cluster = _cluster()
    cluster.themes[0].activation = 50.0
    cluster.themes[1].activation = 0.0
    assert cluster.get_dominant_theme(margin=90.0) is None


def test_top_theme_dominant_when_lead_over_second_meets_margin():
    cluster = _cluster()
    cluster.themes[0].activation = 100.0
    cluster.themes[1].activation = 5.0  # lead of 95 >= 90
    assert cluster.get_dominant_theme(margin=90.0) is cluster.themes[0]


def test_no_dominant_theme_when_lead_over_second_below_margin():
    cluster = _cluster()
    cluster.themes[0].activation = 100.0
    cluster.themes[1].activation = 50.0  # lead of 50 < 90
    assert cluster.get_dominant_theme(margin=90.0) is None


# --- ThemeCluster: get_theme -----------------------------------------------

def test_get_theme_returns_theme_with_matching_relation():
    cluster = _cluster()
    theme = cluster.get_theme("opposite")
    assert theme is not None and theme.relation == "opposite"


def test_get_theme_returns_none_for_unknown_relation():
    cluster = _cluster()
    assert cluster.get_theme("nonexistent") is None


# --- ThemeCluster: intra-cluster spreading ---------------------------------

def test_spread_activation_skips_frozen_cluster():
    cluster = ThemeCluster(THEME_TOP_BRIDGE, "direction", ["identity"])
    cluster.themes[0].activation = 40.0
    cluster.frozen = True
    cluster.spread_activation(_FakeMeta([], _SPREAD_PARAMS, _SPREAD_COEFFS))
    assert cluster.themes[0].activation == 40.0  # untouched


def test_spread_activation_applies_decay_and_self_excitation():
    cluster = ThemeCluster(THEME_TOP_BRIDGE, "direction", ["identity"])
    cluster.themes[0].activation = 40.0
    cluster.spread_activation(_FakeMeta([], _SPREAD_PARAMS, _SPREAD_COEFFS))
    # net_input = -25 (decay) + 40*0.5 (self) = -5
    # alpha = 1.0 * (1/50) * (1/1) = 0.02;  net_effect = round(20*tanh(-0.1)) = -2
    expected = 40.0 + round(20 * math.tanh(0.02 * -5))
    assert cluster.themes[0].activation == expected == 38.0


# --- Themespace: construction & justify mode -------------------------------

def _themespace():
    dims = [_FakeDim("direction", ["identity", "opposite"])]
    meta = _FakeMeta(dims, {"dominant_theme_margin": 90, "theme_boost_amount": 7}, _SPREAD_COEFFS)
    return Themespace(meta)


def test_justify_mode_makes_all_three_bridge_types_possible():
    ts = _themespace()
    ts.set_justify_mode(True)
    assert set(ts.possible_theme_types) == {
        THEME_TOP_BRIDGE,
        THEME_BOTTOM_BRIDGE,
        THEME_VERTICAL_BRIDGE,
    }


def test_default_mode_excludes_bottom_bridge_type():
    ts = _themespace()
    assert THEME_BOTTOM_BRIDGE not in ts.possible_theme_types


def test_thematic_pressure_starts_off():
    """Scheme: active-theme-types is initialised to '() (themes.ss:53)."""
    ts = _themespace()
    assert ts.has_thematic_pressure() is False
    assert ts.active_theme_types == []


def test_leaving_justify_mode_drops_bottom_pressure():
    ts = _themespace()
    ts.set_justify_mode(True)
    ts.thematic_pressure_on()
    assert THEME_BOTTOM_BRIDGE in ts.active_theme_types
    ts.set_justify_mode(False)
    assert THEME_BOTTOM_BRIDGE not in ts.active_theme_types


# --- Themespace: thematic pressure -----------------------------------------

def _top_direction_cluster(ts):
    return next(
        c for c in ts.clusters
        if c.theme_type == THEME_TOP_BRIDGE and c.dimension == "direction"
    )


def test_thematic_pressure_reports_dominant_relation_for_active_type():
    ts = _themespace()
    ts.thematic_pressure_on()
    cluster = _top_direction_cluster(ts)
    cluster.get_theme("identity").activation = 95.0  # single dominant positive
    assert ts.get_thematic_pressure("top") == {"direction": "identity"}


def test_thematic_pressure_empty_while_pressure_is_off():
    ts = _themespace()
    _top_direction_cluster(ts).get_theme("identity").activation = 95.0
    assert ts.get_thematic_pressure("top") == {}


def test_thematic_pressure_empty_for_inactive_bridge_type():
    ts = _themespace()
    ts.thematic_pressure_on()
    # bottom is not among the possible theme types outside justify mode
    assert ts.get_thematic_pressure("bottom") == {}


# --- Themespace: boost / clamp / max ---------------------------------------

def test_boost_theme_raises_the_matching_theme_activation():
    ts = _themespace()
    ts.boost_theme(THEME_TOP_BRIDGE, "direction", "identity", factor=100.0)
    assert _top_direction_cluster(ts).get_theme("identity").activation == 7.0


def test_clamp_negative_pattern_inhibits_matching_theme():
    ts = _themespace()
    ts.clamp_negative_pattern({"direction": "opposite"}, THEME_TOP_BRIDGE)
    theme = _top_direction_cluster(ts).get_theme("opposite")
    assert theme.frozen is True
    assert theme.activation == -100.0


def test_clamping_a_pattern_turns_thematic_pressure_on():
    """§4.2: "the clamping of theme activations ... automatically turns on
    thematic pressure"."""
    ts = _themespace()
    assert ts.has_thematic_pressure() is False
    ts.clamp_negative_pattern({"direction": "opposite"}, THEME_TOP_BRIDGE)
    assert ts.has_thematic_pressure([THEME_TOP_BRIDGE]) is True


def test_unclamp_all_turns_thematic_pressure_off():
    ts = _themespace()
    ts.clamp_negative_pattern({"direction": "opposite"}, THEME_TOP_BRIDGE)
    ts.unclamp_all()
    assert ts.has_thematic_pressure() is False


def test_max_positive_theme_activation_tracks_largest_active_theme():
    ts = _themespace()
    ts.thematic_pressure_on()
    _top_direction_cluster(ts).get_theme("identity").activation = 42.0
    assert ts.get_max_positive_theme_activation() == 42.0


def test_reset_clears_all_theme_activation():
    ts = _themespace()
    _top_direction_cluster(ts).get_theme("identity").activation = 80.0
    ts.reset()
    assert ts.get_max_positive_theme_activation() == 0.0
