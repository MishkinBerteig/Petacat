"""Tests for TemporalTrace."""

from server.engine.trace import TemporalTrace, TraceEvent
from tests.support.standard_names import BOND_BUILT


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


def test_clear():
    trace = TemporalTrace()
    trace.record_event(TraceEvent(BOND_BUILT, 10, 80))
    trace.record_snag(50, 70.0)
    trace.clear()
    assert len(trace.events) == 0
    assert trace.snag_count == 0
