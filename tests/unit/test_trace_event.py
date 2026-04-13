"""Tests for TemporalTrace."""

from server.engine.trace import BOND_BUILT, TemporalTrace, TraceEvent


def test_record_event():
    trace = TemporalTrace()
    event = TraceEvent(BOND_BUILT, codelet_count=10, temperature=80)
    trace.record_event(event)
    assert len(trace.events) == 1


def test_snag_recording():
    trace = TemporalTrace()
    trace.record_snag(50, 70.0, theme_pattern={"dir": "identity"})
    assert trace.snag_count == 1
    assert trace.within_snag_period


def test_get_recent_snags():
    trace = TemporalTrace()
    trace.record_snag(100, 70.0, {"a": "1"})
    trace.record_snag(200, 60.0, {"a": "1"})
    trace.record_snag(300, 50.0, {"b": "2"})
    snags = trace.get_recent_snags()
    assert len(snags) == 3


def test_clamp_tracking():
    trace = TemporalTrace()
    trace.record_clamp_start(100, 80.0)
    assert trace.within_clamp_period
    assert trace.clamp_count == 1
    trace.record_clamp_end(200, 70.0)
    assert not trace.within_clamp_period


def test_clear():
    trace = TemporalTrace()
    trace.record_event(TraceEvent(BOND_BUILT, 10, 80))
    trace.record_snag(50, 70.0)
    trace.clear()
    assert len(trace.events) == 0
    assert trace.snag_count == 0
