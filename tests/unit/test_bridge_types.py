"""The bridge-type and orientation constants."""

from server.engine.bridges import (
    BRIDGE_BOTTOM,
    BRIDGE_TOP,
    BRIDGE_VERTICAL,
    ORIENTATION_HORIZONTAL,
    ORIENTATION_VERTICAL,
)


def test_bridge_type_constants_are_strings():
    assert isinstance(BRIDGE_TOP, str)
    assert isinstance(BRIDGE_BOTTOM, str)
    assert isinstance(BRIDGE_VERTICAL, str)


def test_orientation_constants_are_strings():
    assert isinstance(ORIENTATION_HORIZONTAL, str)
    assert isinstance(ORIENTATION_VERTICAL, str)
