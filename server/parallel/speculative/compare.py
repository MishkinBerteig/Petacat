"""Run a problem under the faithful loop, the SSR, or the speculative engine, and compare.

The record a run leaves is everything an observer of the engine could see, in the order
it saw it: every codelet (type, id, count), every structure the sink was told was built
or broken, every Trace event, every answer, the final status and a fingerprint of the
final shared state.  Two executions are *equal* only if all of it is equal.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from server.engine.runner import EngineRunner
from server.parallel.speculative.fingerprint import combined, fingerprint


class RecordingSink:
    """A ``RunSink`` that remembers every call, compactly and in order."""

    def __init__(self) -> None:
        self.steps: list[tuple] = []
        self.structures: list[tuple] = []
        self.events: list[tuple] = []
        self.answers: list[tuple] = []
        self.calls: list[str] = []

    def on_run_created(self, ctx: Any) -> None:
        self.calls.append("created")

    def on_codelet(self, ctx: Any, codelet: Any, result: Any) -> None:
        self.steps.append((codelet.codelet_type, codelet.id, result.codelet_count,
                           result.answer_found, result.gave_up))

    def on_trace_event(self, ctx: Any, event: Any) -> None:
        self.events.append((
            event.event_type, event.codelet_count, round(float(event.temperature), 9),
            event.description, getattr(event, "event_number", None),
        ))

    def on_structure_change(self, ctx: Any, structure: Any, change: str) -> None:
        self.structures.append((type(structure).__name__, getattr(structure, "id", None), change))

    def on_answer(self, ctx: Any, answer: str, quality: float) -> None:
        self.answers.append((answer, quality))

    def on_valence(self, ctx: Any, signal: str, strength: float) -> None:
        self.calls.append("valence")

    def on_turn_end(self, ctx: Any) -> None:
        self.calls.append("turn_end")


@dataclass
class RunRecord:
    mode: str
    status: str = ""
    answers: list[str] = field(default_factory=list)
    codelet_count: int = 0
    steps: list[tuple] = field(default_factory=list)
    structures: list[tuple] = field(default_factory=list)
    events: list[tuple] = field(default_factory=list)
    sink_answers: list[tuple] = field(default_factory=list)
    calls: list[str] = field(default_factory=list)
    final: dict[str, str] = field(default_factory=dict)
    digest: str = ""
    telemetry: dict[str, Any] | None = None
    seconds: float = 0.0


def run_record(
    meta: Any,
    problem: tuple,
    seed: int,
    mode: str,
    workers: int = 1,
    max_steps: int = 0,
    *,
    update: str = "engine",
    update_threads: int = 1,
    **engine_options: Any,
) -> RunRecord:
    """Execute one run and return its record.

    ``mode`` is ``"faithful"`` (``run_mcat``), ``"ssr"`` or ``"spec"``.
    """
    import time

    from server.parallel.speculative.engine import SpeculativeEngine
    from server.parallel.speculative.reference import StreamSerial

    initial, modified, target, answer = problem
    sink = RecordingSink()
    runner = EngineRunner(meta)
    runner.init_mcat(initial, modified, target, answer, seed=seed, sink=sink)
    rec = RunRecord(mode=mode)
    t0 = time.perf_counter()
    if mode == "faithful":
        result = runner.run_mcat(max_steps)
    elif mode == "ssr":
        ssr = StreamSerial(runner, update=update, update_threads=update_threads)
        try:
            result = ssr.run(max_steps)
        finally:
            ssr.close()
    elif mode == "spec":
        engine = SpeculativeEngine(
            runner, workers, update=update, update_threads=update_threads, **engine_options
        )
        try:
            result = engine.run(max_steps)
            rec.telemetry = engine.telemetry
        finally:
            engine.close()
    else:
        raise ValueError(mode)
    rec.seconds = time.perf_counter() - t0
    rec.status = result.status
    rec.answers = list(result.answers)
    rec.codelet_count = result.codelet_count
    rec.steps = sink.steps
    rec.structures = sink.structures
    rec.events = sink.events
    rec.sink_answers = sink.answers
    rec.calls = sink.calls
    rec.final = fingerprint(runner.ctx)
    rec.digest = combined(runner.ctx)
    return rec


def diff(a: RunRecord, b: RunRecord) -> list[str]:
    """Human-readable differences between two records ([] when identical)."""
    out: list[str] = []
    for name in ("status", "answers", "codelet_count", "sink_answers", "calls"):
        if getattr(a, name) != getattr(b, name):
            out.append(f"{name}: {getattr(a, name)!r} != {getattr(b, name)!r}")
    for name in ("steps", "structures", "events"):
        xs, ys = getattr(a, name), getattr(b, name)
        if xs != ys:
            n = next((i for i, (x, y) in enumerate(zip(xs, ys)) if x != y), min(len(xs), len(ys)))
            out.append(
                f"{name}: first difference at index {n} "
                f"({xs[n] if n < len(xs) else None!r} vs {ys[n] if n < len(ys) else None!r}); "
                f"lengths {len(xs)} / {len(ys)}"
            )
    for comp in sorted(set(a.final) | set(b.final)):
        if a.final.get(comp) != b.final.get(comp):
            out.append(f"final state differs in component {comp!r}")
    return out
