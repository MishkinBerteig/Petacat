"""Tests for Theme/Themespace with string type constants."""

from server.engine.themes import (
    ALL_THEME_TYPES,
    THEME_BOTTOM_BRIDGE,
    THEME_TOP_BRIDGE,
    THEME_VERTICAL_BRIDGE,
    Theme,
    ThemeCluster,
)


def test_theme_type_constants_are_strings():
    assert isinstance(THEME_TOP_BRIDGE, str)
    assert isinstance(THEME_BOTTOM_BRIDGE, str)
    assert isinstance(THEME_VERTICAL_BRIDGE, str)


def test_all_theme_types_list():
    assert len(ALL_THEME_TYPES) == 3
    assert THEME_TOP_BRIDGE in ALL_THEME_TYPES
    assert THEME_BOTTOM_BRIDGE in ALL_THEME_TYPES
    assert THEME_VERTICAL_BRIDGE in ALL_THEME_TYPES


def test_theme_stores_string_type():
    theme = Theme(THEME_TOP_BRIDGE, "plato-direction-category", "identity")
    assert theme.theme_type == "top_bridge"
    assert isinstance(theme.theme_type, str)


def test_theme_cluster_stores_string_type():
    cluster = ThemeCluster(THEME_VERTICAL_BRIDGE, "plato-direction-category", ["identity", "opposite"])
    assert cluster.theme_type == "vertical_bridge"
    assert len(cluster.themes) == 2
    for theme in cluster.themes:
        assert theme.theme_type == "vertical_bridge"


def test_theme_repr_contains_string_type():
    theme = Theme(THEME_BOTTOM_BRIDGE, "plato-direction-category", "identity")
    assert "bottom_bridge" in repr(theme)


def test_cluster_repr_contains_string_type():
    cluster = ThemeCluster(THEME_TOP_BRIDGE, "plato-direction-category", ["identity"])
    assert "top_bridge" in repr(cluster)
