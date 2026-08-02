"""Temperature's own state: its starting value and its clamp."""

from server.engine.temperature import Temperature


def test_initial_temperature():
    t = Temperature(100.0)
    assert t.value == 100.0
    assert not t.clamped


def test_clamp():
    t = Temperature(100.0)
    t.clamp(50.0, 3)
    assert t.clamped
    assert t.value == 50.0


def test_tick_clamp_expiration():
    t = Temperature(100.0)
    t.clamp(50.0, 2)
    t.tick_clamp()
    assert t.clamped
    t.tick_clamp()
    assert not t.clamped
