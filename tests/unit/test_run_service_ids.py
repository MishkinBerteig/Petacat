"""A service action on a live run numbers its trace events from the run's own allocator.

``EngineRunner`` binds ``ctx.ids`` around every step.  ``RunService``'s clamp, undo and
Self-watching actions run between steps, and a clamp makes a trace event that takes an
``event_number``.  The service opens the run's scope around each of them (``_in_run_scope``), so the
number is the run's own.  It used to come from a process-wide fallback, which depended on what else
the process had run and could collide with the run's own numbers; that fallback no longer exists.
"""

from __future__ import annotations

import dataclasses
from types import SimpleNamespace

import pytest

from server.engine.codelet_patterns import pattern_entries
from server.engine.ids import KIND_TRACE_EVENT
from server.engine.memory import EpisodicMemory
from server.engine.numeric.backend import use_backend
from server.engine.rng import RNG
from server.engine.runner import EngineRunner
from server.services.run_service import RunService
from tests.support import golden_baseline as gb

pytestmark = pytest.mark.numeric_matrix


def _service_with_a_run(steps: int = 60):
    meta = gb.load_meta()
    runner = EngineRunner(meta)
    with use_backend("off"):
        runner.init_mcat("abc", "abd", "xyz", seed=1, memory=EpisodicMemory(), rng=RNG(1),
                         parameters={"initial_clamp_fixed_time": True})
        runner.run_mcat(max_steps=steps)
    service = RunService.__new__(RunService)
    service._runners = {7: runner}
    service._sinks = {}
    return service, runner


def test_a_codelet_pattern_clamp_reads_the_configuration_the_run_holds() -> None:
    """A run holds its configuration for life, so an Admin edit since it began must not reach a
    person's clamp of that run, and an Audit replay under the run's own configuration must agree."""
    service, runner = _service_with_a_run()
    held = runner.ctx.meta
    edited = dataclasses.replace(held, urgency_levels={k: v + 1 for k, v in held.urgency_levels.items()})
    service._store = SimpleNamespace(current=lambda: edited)

    clamped = service.clamp_codelet_pattern(7, "bottom_up")["clamped"]

    assert clamped == [
        {"codelet_type": codelet_type, "urgency": int(held.get_urgency(level))}
        for codelet_type, level in pattern_entries(held, "bottom_up")
    ]
    service.unclamp_codelet_pattern(7, "bottom_up")


def _event_numbers(runner) -> list[int]:
    return [e.event_number for e in runner.ctx.trace.events]


@pytest.mark.parametrize("action", ["clamp_codelet_pattern", "clamp_theme_pattern", "undo_last_clamp_after_clamp"])
def test_a_clamp_takes_its_event_number_from_the_runs_allocator(action) -> None:
    service, runner = _service_with_a_run()
    run_before = runner.ctx.ids.snapshot().get(KIND_TRACE_EVENT, 0)
    before = set(_event_numbers(runner))

    if action == "clamp_codelet_pattern":
        service.clamp_codelet_pattern(7, "bottom_up")
    elif action == "clamp_theme_pattern":
        service.clamp_theme_pattern(7, [{"type": "top_bridge", "themes": [
            {"dimension": "plato-letter-category", "relation": "identity", "activation": 100.0}]}])
    else:
        service.clamp_codelet_pattern(7, "bottom_up")
        service.undo_last_clamp(7)

    new = [n for n in _event_numbers(runner) if n not in before]
    assert new, "the action made no trace event"
    assert runner.ctx.ids.snapshot().get(KIND_TRACE_EVENT, 0) > run_before
    numbers = _event_numbers(runner)
    assert len(numbers) == len(set(numbers)), "an event number collided with the run's own"
    assert all(n <= runner.ctx.ids.snapshot()[KIND_TRACE_EVENT] for n in numbers)
