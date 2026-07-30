"""The ``RunSink`` port (WP3.2).

The port's whole job is to keep the engine ignorant of its persistence mode, so what
is worth testing is the shape of the contract rather than any behaviour: that the
protocol names the events the plan says it names, that ``NullSink`` satisfies it, and
that a recording sink sees what it is supposed to see.

The event vocabulary is asserted by name deliberately. It is the interface three
implementations and every later phase attach to, so a method quietly renamed or
dropped should fail here rather than in whichever mode happened to use it.
"""

from __future__ import annotations

import inspect

import pytest

from server.engine.sink import (
    STRUCTURE_BROKEN,
    STRUCTURE_BUILT,
    VALENCE_LOVE,
    VALENCE_NOT_LOVE,
    NullSink,
    RunSink,
)

EXPECTED_EVENTS = {
    "on_run_created",
    "on_codelet",
    "on_trace_event",
    "on_structure_change",
    "on_answer",
    "on_valence",
    "on_turn_end",
}


def _protocol_methods(protocol) -> set[str]:
    return {
        name
        for name in dir(protocol)
        if not name.startswith("_") and callable(getattr(protocol, name, None))
    }


def test_protocol_declares_exactly_the_planned_events():
    assert _protocol_methods(RunSink) == EXPECTED_EVENTS


def test_null_sink_satisfies_the_protocol():
    assert isinstance(NullSink(), RunSink)


def test_null_sink_implements_every_event():
    """A missing method would only surface when some mode happened to emit it."""
    assert EXPECTED_EVENTS <= {name for name, _ in inspect.getmembers(NullSink(), callable)}


def test_every_event_takes_the_live_context_first():
    """Events carry the context, never a pre-serialised payload.

    This is what makes Fast Run able to build nothing: a sink that is handed a payload
    forces the payload to be constructed whether or not anyone stores it.
    """
    for name in EXPECTED_EVENTS:
        params = list(inspect.signature(getattr(RunSink, name)).parameters)
        assert params[0] == "self"
        assert params[1] == "ctx", f"{name} does not take ctx first: {params}"


def test_no_event_is_a_coroutine():
    """The engine's loop is synchronous; a sink that must be awaited would re-introduce
    the per-codelet coroutine WP3.3 exists to remove."""
    for name in EXPECTED_EVENTS:
        assert not inspect.iscoroutinefunction(getattr(NullSink, name))


def test_null_sink_is_slotted_and_accumulates_nothing():
    """Fast Run's requirement is that nothing storable is built.

    ``__slots__`` with no entries means a NullSink cannot grow an attribute to
    accumulate into, so the "buffer now, write later" mistake cannot be made here
    without the change being visible.
    """
    sink = NullSink()
    assert NullSink.__slots__ == ()
    with pytest.raises(AttributeError):
        sink.records = []


def test_constants_are_distinct():
    assert STRUCTURE_BUILT != STRUCTURE_BROKEN
    assert VALENCE_LOVE != VALENCE_NOT_LOVE


def test_a_recording_sink_satisfies_the_protocol_without_inheriting():
    """The port is structural, so the service layer need not import the engine to
    implement it — which is what keeps the dependency pointing one way."""

    class Recorder:
        def __init__(self) -> None:
            self.seen: list[str] = []

        def on_run_created(self, ctx): self.seen.append("run_created")
        def on_codelet(self, ctx, codelet, result): self.seen.append("codelet")
        def on_trace_event(self, ctx, event): self.seen.append("trace_event")
        def on_structure_change(self, ctx, structure, change): self.seen.append(change)
        def on_answer(self, ctx, answer, quality): self.seen.append("answer")
        def on_valence(self, ctx, signal, strength): self.seen.append(signal)
        def on_turn_end(self, ctx): self.seen.append("turn_end")

    recorder = Recorder()
    assert isinstance(recorder, RunSink)

    recorder.on_run_created(None)
    recorder.on_structure_change(None, None, STRUCTURE_BUILT)
    recorder.on_valence(None, VALENCE_LOVE, 1.0)
    recorder.on_turn_end(None)
    assert recorder.seen == ["run_created", STRUCTURE_BUILT, VALENCE_LOVE, "turn_end"]
