"""Tests for Bridge with string type constants."""

import os
import pytest

from server.engine.bridges import (
    BRIDGE_BOTTOM,
    BRIDGE_TOP,
    BRIDGE_VERTICAL,
    ORIENTATION_HORIZONTAL,
    ORIENTATION_VERTICAL,
    Bridge,
)
from server.engine.metadata import MetadataProvider
from server.engine.slipnet import Slipnet
from server.engine.workspace import Workspace


SEED_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "seed_data")


@pytest.fixture
def workspace():
    meta = MetadataProvider.from_seed_data(SEED_DIR)
    slipnet = Slipnet.from_metadata(meta)
    return Workspace("abc", "abd", "xyz", None, slipnet)


def test_bridge_type_constants_are_strings():
    assert isinstance(BRIDGE_TOP, str)
    assert isinstance(BRIDGE_BOTTOM, str)
    assert isinstance(BRIDGE_VERTICAL, str)


def test_orientation_constants_are_strings():
    assert isinstance(ORIENTATION_HORIZONTAL, str)
    assert isinstance(ORIENTATION_VERTICAL, str)


def test_top_bridge_is_horizontal(workspace):
    obj1 = workspace.initial_string.objects[0]
    obj2 = workspace.modified_string.objects[0]
    bridge = Bridge(obj1, obj2, BRIDGE_TOP, [])
    assert bridge.bridge_type == "top"
    assert bridge.orientation == ORIENTATION_HORIZONTAL
    assert bridge.is_horizontal
    assert not bridge.is_vertical


def test_bottom_bridge_is_horizontal(workspace):
    obj1 = workspace.target_string.objects[0]
    obj2 = workspace.initial_string.objects[0]  # Placeholder
    bridge = Bridge(obj1, obj2, BRIDGE_BOTTOM, [])
    assert bridge.bridge_type == "bottom"
    assert bridge.is_horizontal


def test_vertical_bridge_is_vertical(workspace):
    obj1 = workspace.initial_string.objects[0]
    obj2 = workspace.target_string.objects[0]
    bridge = Bridge(obj1, obj2, BRIDGE_VERTICAL, [])
    assert bridge.bridge_type == "vertical"
    assert bridge.orientation == ORIENTATION_VERTICAL
    assert bridge.is_vertical
    assert not bridge.is_horizontal


def test_bridge_repr_contains_type(workspace):
    obj1 = workspace.initial_string.objects[0]
    obj2 = workspace.modified_string.objects[0]
    bridge = Bridge(obj1, obj2, BRIDGE_TOP, [])
    assert "top" in repr(bridge)
