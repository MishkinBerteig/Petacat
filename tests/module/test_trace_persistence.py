"""Module tests for trace event persistence logic.

Tests that stepping the engine produces trace events that can be
serialized correctly. The actual DB persistence is tested in e2e tests;
here we verify the in-memory trace events have the right shape for
persistence.
"""

import os
import pytest

from server.engine.metadata import MetadataProvider
from server.engine.runner import EngineRunner
from server.engine.trace import (
    BOND_BUILT,
    BOND_BROKEN,
    SNAG,
    ANSWER_FOUND,
    TraceEvent,
    TemporalTrace,
)


SEED_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "seed_data")


@pytest.fixture
def meta():
    return MetadataProvider.from_seed_data(SEED_DIR)


def test_trace_events_have_string_types():
    """All event types should be plain strings, suitable for DB storage."""
    trace = TemporalTrace()
    event = TraceEvent(BOND_BUILT, codelet_count=10, temperature=80.0)
    trace.record_event(event)

    assert isinstance(event.event_type, str)
    assert event.event_type == "bond_built"


def test_trace_event_serializable_shape():
    """Trace events should have all fields needed for TraceEventRow."""
    event = TraceEvent(
        SNAG,
        codelet_count=50,
        temperature=70.0,
        description="Test snag",
        theme_pattern={"direction": "identity"},
    )
    # These are the fields that _persist_new_trace_events writes to DB
    assert hasattr(event, "event_number")
    assert hasattr(event, "event_type")
    assert hasattr(event, "codelet_count")
    assert hasattr(event, "temperature")
    assert hasattr(event, "description")
    assert hasattr(event, "theme_pattern")
    assert isinstance(event.event_number, int)
    assert isinstance(event.event_type, str)


def test_running_produces_trace_events(meta):
    """Running the engine should produce trace events with string types."""
    runner = EngineRunner(meta)
    runner.init_mcat("abc", "abd", "xyz", seed=42)
    runner.run_mcat(max_steps=200)

    events = runner.ctx.trace.events
    assert len(events) > 0

    for event in events:
        assert isinstance(event.event_type, str), f"Event type should be string, got {type(event.event_type)}"
        assert isinstance(event.codelet_count, int)
        assert isinstance(event.temperature, float)
        assert isinstance(event.event_number, int)


def test_trace_events_include_expected_types(meta):
    """After a decent run, we should see at least bond and description events."""
    runner = EngineRunner(meta)
    runner.init_mcat("abc", "abd", "xyz", seed=42)
    runner.run_mcat(max_steps=500)

    event_types = {e.event_type for e in runner.ctx.trace.events}
    # After 500 steps, we should see at least some structure-building events
    assert len(event_types) > 0
    # Bond building is very common in early exploration
    assert "bond_built" in event_types or "description_built" in event_types


def test_snag_events_have_theme_pattern():
    """Snag events recorded via record_snag should include theme_pattern."""
    trace = TemporalTrace()
    pattern = {"direction": "identity", "category": "sameness"}
    trace.record_snag(100, 70.0, theme_pattern=pattern)

    snags = trace.get_recent_snags()
    assert len(snags) == 1
    assert snags[0].event_type == "snag"
    assert snags[0].theme_pattern == pattern


def test_step_produces_incrementing_event_numbers(meta):
    """Event numbers should be unique and incrementing."""
    runner = EngineRunner(meta)
    runner.init_mcat("abc", "abd", "xyz", seed=42)
    runner.run_mcat(max_steps=100)

    events = runner.ctx.trace.events
    if len(events) >= 2:
        for i in range(1, len(events)):
            assert events[i].event_number > events[i - 1].event_number


def test_trace_diff_captures_new_events(meta):
    """Diffing trace length before/after step captures exactly the new events."""
    runner = EngineRunner(meta)
    runner.init_mcat("abc", "abd", "xyz", seed=42)

    # Run a few steps to generate some events
    for _ in range(100):
        before = len(runner.ctx.trace.events)
        runner.step_mcat()
        after = len(runner.ctx.trace.events)
        new_events = runner.ctx.trace.events[before:after]
        # Each new event should be well-formed
        for e in new_events:
            assert isinstance(e.event_type, str)
            assert e.codelet_count >= 0
