#!/usr/bin/env python3
"""Benchmark the Petacat engine — the profile behind Phase 0 section B2.

The Phase 0 plan rests on a small number of measured quantities: how fast the engine
runs, where the time goes, what fraction of it is parallelisable, what a snapshot
costs, and how full the coderack is.  Those numbers decide which work is worth doing —
section B2(a) concludes that fixing one function beats parallelising codelets, and
B2(b) puts an arithmetic ceiling on what parallelism can return.  A conclusion that
strong should not rest on a measurement nobody can repeat, so this script is that
measurement, checked in.

Every later work package reports its effect through this script.  WP1.1 makes coderack
eviction incremental and is judged by the eviction rows here; WP1.2 explicitly
recomputes the Amdahl fractions, which is why they are computed rather than quoted.
The plan's own figures are carried as a reference column so that "reproduces the B2
table within noise" is something the output shows rather than something a reader has
to work out.

What is measured, and how
-------------------------
Four sections, each a separate pass, because they need different conditions:

``throughput``
    Codelets per second on the plan's reference problems, with **no instrumentation
    installed at all**.  This is the number that describes the engine; the per-phase
    pass cannot produce it, because measuring the parts perturbs the whole.

``phases``
    Per-phase timings on the profile problem, with wrappers installed.  Timings are
    **inclusive**, so nested and overlapping phases both appear at full cost:
    ``remove_old_codelets`` is inside ``coderack.post``, and the two posting rows are
    what *call* ``coderack.post``.  The plan flags this and it is preserved here rather
    than smoothed away, because the alternative — exclusive timings — would hide that
    eviction is reached through posting.  Only the four ``numeric:`` rows are disjoint,
    which is why they are the only rows summed into a total.

``counters``
    Call and occupancy counts, with counting wrappers but no timers.  Counting is
    separated from timing because ``_urgency_to_bin`` is called ~324,000 times and
    wrapping it costs more than several of the phases being measured.  These counts are
    exact, not sampled: for a fixed seed the engine is deterministic, so one run
    suffices.

``snapshot``
    Size and cost of the seven ``serialize_*`` functions, sampled at every update cycle
    exactly as ``run_service`` would.  See "The snapshot section" below.

The numeric substrate has its own script
----------------------------------------
``scripts/bench_numeric.py`` measures the GPU substrate (WP4.5): the scaling curve
of activation spreading at 59, 10³, 10⁴ and 10⁵ synthetic nodes, and the crossover
where the GPU overtakes vectorised CPU.  It is separate rather than a fifth section
here because its conventions have to differ — a Metal kernel must be *warmed* and
then timed, where every section below runs in a fresh interpreter precisely so that
nothing is warm — and because it needs NumPy and MLX, which this script deliberately
does not.  The ``numeric:`` rows in the phase table below remain the right place to
read the substrate's effect on a real 59-node run.

Why each repeat runs in a fresh interpreter
-------------------------------------------
Measured on the profile problem, the first run in a process took ~280 ms and every
subsequent run in the same process took ~305 ms, with the difference concentrated almost
entirely in ``update_all_object_values`` (~30 ms rising to ~42 ms).  Nothing leaks — the
tracked
object count is identical — so this looks like allocator and GC-generation state rather
than engine state.  It is nonetheless a 9% swing on the total and a 40% swing on one
row, which is larger than most of the differences later work packages will be asked to
detect.  Running each repeat in a fresh interpreter removes it, and has the side benefit
of removing the process-history dependence that defect D3 describes.

Repeats therefore measure real run-to-run variation rather than position-in-process.

Why the fastest repeat is reported, not the median
--------------------------------------------------
The headline figure for every timing is the **fastest** repeat, with the full observed
range printed beside it.  This is the standard choice for a CPU-bound benchmark on a
shared machine, and for the usual reason: contention, scheduling and thermal effects can
only ever *add* time, so the distribution has a hard floor near the true cost and an
unbounded tail.  The median tracks how busy the machine was; the minimum tracks the
engine.  Measured here, three invocations minutes apart on a loaded machine reported
253, 287 and 406 ms as medians for the same unchanged code — differences far larger
than anything a work package is likely to be asked to detect.

The per-phase table reports the single fastest repeat *as a whole*, rather than each
row's own minimum, so that the rows remain a coherent account of one run and the
percentages and Amdahl fractions stay internally consistent.

The load average at the start and end of the run is recorded, and a warning is printed
when the machine is busy enough for the numbers to be worth repeating.

The snapshot section
--------------------
The ``serialize_*`` functions are imported from ``server.engine.serialization`` and
nothing else is needed to reach them — no session, no driver, no ORM.

That was not always so.  They used to live in ``server/services/snapshot_service.py``
alongside ``sqlalchemy`` and ``server.models`` imports (defect D2 in the plan), so
measuring them here meant importing the database layer, which on a local checkout was
generally not installed.  This script carried a shim that stubbed out the four names
the service module imported but the serializers never used, purely so the section could
run.  WP3.1 split the module and the shim went with it; the section now imports the
serializers the same way any other caller does, and is skipped with the reason reported
if that import somehow fails.

Usage
-----
    python3 scripts/bench_engine.py [--problems SPEC,...] [--profile-problem SPEC]
                                    [--repeats N] [--sections LIST] [--json PATH]
                                    [--baseline PATH] [--quiet]

A problem spec is ``initial:modified:target@seed``; ``->`` and ``;`` are accepted in
place of the colons, so ``'abc->abd;mrrjjj@42'`` works if the shell quotes it.
"""

from __future__ import annotations

import argparse
import importlib
import json
import multiprocessing
import os
import platform
import statistics
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timezone
from typing import Any, Callable

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

SEED_DIR = os.path.join(REPO, "seed_data")

#: Per-run codelet cap, matching ``scripts/build_expected_range.py``.  None of the
#: reference problems comes close to it; it exists so a pathological change cannot turn
#: a benchmark into a hang.
MAX_STEPS = 6000

SECTIONS = ("throughput", "phases", "counters", "snapshot")


# ──────────────────────────────────────────────────────────────────────────────
# The plan's figures, carried as a reference column
#
# These are the Phase 0 baseline as measured before WP1.1.  They are a fixed point of
# comparison, not a target: WP1.1 is *expected* to move the eviction and Amdahl rows a
# long way, and at that point ``--baseline`` against a previous JSON record is the more
# useful comparison.
#
# Use ``--baseline`` rather than these constants whenever the question is "did my change
# help".  A worked example of why: WP0.3 replaces five class-level ``_next_id`` counters
# with per-run allocation, for reasons of correctness alone — and measured with this
# script it is worth ~9% of runtime on its own, because writing a class attribute on
# every ``Codelet()`` invalidates CPython's type version tag and de-specialises every
# attribute load on ``Codelet``.  ``remove_old_codelets`` performs ~318,000 of those
# loads, and drops from 96 ms to 80 ms when the write goes away.  A change measured
# against these constants rather than against the tree it landed on would have credited
# that 9% to whatever happened to be measured next.
# ──────────────────────────────────────────────────────────────────────────────

PLAN_THROUGHPUT: dict[tuple[str, str, str, int], dict[str, Any]] = {
    ("abc", "abd", "ijk", 1): {"codelets": 392, "wall_ms": 45, "rate": 8657,
                               "trace_events": 6, "snapshots": 26},
    ("abc", "abd", "xyz", 7): {"codelets": 740, "wall_ms": 87, "rate": 8518,
                               "trace_events": 4, "snapshots": 49},
    ("abc", "abd", "xyz", 42): {"codelets": 797, "wall_ms": 82, "rate": 9774,
                                "trace_events": 8, "snapshots": 53},
    ("abc", "abd", "iijjkk", 42): {"codelets": 1416, "wall_ms": 203, "rate": 6994,
                                   "trace_events": 14, "snapshots": 94},
    ("abc", "abd", "mrrjjj", 42): {"codelets": 2229, "wall_ms": 292, "rate": 7641,
                                   "trace_events": 18, "snapshots": 148},
}

#: Total wall time of the plan's *instrumented* profile run.  Percentages in the B2
#: table are taken against this, not against the 292 ms uninstrumented figure.
PLAN_PROFILE_TOTAL_MS = 280.0

PLAN_SNAPSHOT = {
    "bytes": 43 * 1024,
    "serialize_ms_low": 0.37,
    "serialize_ms_high": 0.46,
    "components_pct": {
        "themespace": 39.0,
        "coderack": 24.0,
        "slipnet": 16.0,
        "rng": 12.0,
        "workspace": 8.0,
    },
}

PLAN_OCCUPANCY = {
    "posts_at_capacity_pct": 58.0,
    "median_occupancy": 100,
    "evictions": 3184,
    "urgency_to_bin_calls": 323883,
}


# ──────────────────────────────────────────────────────────────────────────────
# The phases
#
# Each row names one method to wrap.  ``group`` decides how the row is used:
#
#   coderack / codelets / posting  — reported, never summed (they overlap each other)
#   numeric                        — reported and summed into the numeric substrate
#   extra                          — reported below the table, absent from B2
#
# ``nested_in`` only affects presentation: it draws the row indented under its parent,
# as the plan's table does, to make the containment visible.
# ──────────────────────────────────────────────────────────────────────────────

PHASES: list[dict[str, Any]] = [
    {
        "key": "coderack.post",
        "label": "coderack.post (including eviction)",
        "target": ("server.engine.coderack", "Coderack", "post"),
        "group": "coderack",
        "plan_ms": 104.4,
    },
    {
        "key": "coderack.remove_old_codelets",
        "label": "remove_old_codelets",
        "target": ("server.engine.coderack", "Coderack", "remove_old_codelets"),
        "group": "coderack",
        "nested_in": "coderack.post",
        "plan_ms": 100.1,
    },
    {
        "key": "codelet_execution",
        "label": "Codelet execution",
        "target": ("server.engine.runner", "EngineRunner", "_execute_codelet"),
        "group": "codelets",
        "plan_ms": 76.9,
    },
    {
        "key": "posting.bottom_up",
        "label": "posting: bottom-up",
        "target": ("server.engine.runner", "EngineRunner", "_post_bottom_up_codelets"),
        "group": "posting",
        "plan_ms": 64.8,
    },
    {
        "key": "posting.top_down",
        "label": "posting: top-down",
        "target": ("server.engine.runner", "EngineRunner", "_post_top_down_codelets"),
        "group": "posting",
        "plan_ms": 53.6,
    },
    {
        "key": "numeric.object_values",
        "label": "numeric: object values",
        "target": ("server.engine.workspace", "Workspace", "update_all_object_values"),
        "group": "numeric",
        "plan_ms": 29.3,
    },
    {
        "key": "numeric.structure_strengths",
        "label": "numeric: structure strengths",
        "target": ("server.engine.workspace", "Workspace",
                   "update_all_structure_strengths"),
        "group": "numeric",
        "plan_ms": 21.7,
    },
    {
        "key": "coderack.choose_and_remove",
        "label": "coderack.choose_and_remove",
        "target": ("server.engine.coderack", "Coderack", "choose_and_remove"),
        "group": "coderack",
        "plan_ms": 8.3,
    },
    {
        "key": "numeric.themespace_spread",
        "label": "numeric: themespace spread",
        "target": ("server.engine.themes", "Themespace", "spread_activation"),
        "group": "numeric",
        "plan_ms": 7.0,
    },
    {
        "key": "numeric.temperature",
        "label": "numeric: temperature",
        "target": ("server.engine.temperature", "Temperature", "update"),
        "group": "numeric",
        "plan_ms": 0.2,
    },
    # Below here: numeric work the B2 table does not list.  Reported separately and
    # deliberately excluded from the numeric-substrate total, so the total keeps the
    # plan's definition and the Amdahl fractions stay comparable with it.
    {
        "key": "extra.slipnet_update",
        "label": "slipnet: decay, spread, jump",
        "target": ("server.engine.slipnet", "Slipnet", "update_activations"),
        "group": "extra",
        "plan_ms": None,
    },
    {
        "key": "extra.workspace_to_themespace",
        "label": "themespace: boost from built bridges",
        "target": ("server.engine.runner", "EngineRunner",
                   "_spread_activation_to_themespace"),
        "group": "extra",
        "plan_ms": None,
    },
    {
        "key": "extra.theme_to_slipnet",
        "label": "themespace: spread to slipnet",
        "target": ("server.engine.themes", "Themespace", "spread_activation_to_slipnet"),
        "group": "extra",
        "plan_ms": None,
    },
]

PHASES_BY_KEY = {p["key"]: p for p in PHASES}


# ──────────────────────────────────────────────────────────────────────────────
# Problem specs
# ──────────────────────────────────────────────────────────────────────────────

DEFAULT_PROBLEMS = [
    "abc:abd:ijk@1",
    "abc:abd:xyz@7",
    "abc:abd:xyz@42",
    "abc:abd:iijjkk@42",
    "abc:abd:mrrjjj@42",
]

#: The plan profiles the largest of the reference problems, which is also the one whose
#: codelet count and cycle count are quoted throughout section B2.
DEFAULT_PROFILE_PROBLEM = "abc:abd:mrrjjj@42"


def parse_problem(spec: str) -> dict[str, Any]:
    """Parse ``initial:modified:target@seed``, tolerating ``->`` and ``;``."""
    body, at, seed_text = spec.partition("@")
    normalised = body.replace("->", ":").replace(";", ":").replace(" ", "")
    parts = [p for p in normalised.split(":") if p]
    if len(parts) != 3:
        raise argparse.ArgumentTypeError(
            f"problem spec {spec!r} should be initial:modified:target@seed"
        )
    try:
        seed = int(seed_text) if at else 0
    except ValueError:
        raise argparse.ArgumentTypeError(f"seed in {spec!r} is not an integer") from None
    return {
        "initial": parts[0],
        "modified": parts[1],
        "target": parts[2],
        "seed": seed,
        "label": f"{parts[0]}->{parts[1]}; {parts[2]}?  seed {seed}",
    }


def _plan_key(problem: dict[str, Any]) -> tuple[str, str, str, int]:
    return (problem["initial"], problem["modified"], problem["target"], problem["seed"])


# ──────────────────────────────────────────────────────────────────────────────
# Worker side — everything below runs in a fresh interpreter, one task per process
#
# These functions are module-level and take plain dicts because ``spawn`` pickles both
# the callable reference and its argument.
# ──────────────────────────────────────────────────────────────────────────────

_META: Any = None


def _meta() -> Any:
    """Load metadata once per worker process (~1-2 ms from JSON)."""
    global _META
    if _META is None:
        from server.engine.metadata import MetadataProvider

        _META = MetadataProvider.from_seed_data(SEED_DIR)
    return _META


def _fresh_runner(problem: dict[str, Any]) -> Any:
    from server.engine.runner import EngineRunner

    runner = EngineRunner(_meta())
    runner.init_mcat(
        problem["initial"], problem["modified"], problem["target"], seed=problem["seed"]
    )
    return runner


def _run_outcome(runner: Any) -> dict[str, Any]:
    ctx = runner.ctx
    ucl = ctx.meta.get_param("update_cycle_length", 15)
    return {
        "status": runner.status,
        "codelets": ctx.codelet_count,
        "answer": ctx.workspace.answer_string.text if ctx.workspace.answer_string else None,
        "trace_events": len(ctx.trace.events),
        "update_cycles": ctx.codelet_count // ucl,
    }


def task_throughput(problem: dict[str, Any]) -> dict[str, Any]:
    """One uninstrumented run.  Nothing is wrapped, so this is the engine's own rate."""
    runner = _fresh_runner(problem)
    started = time.perf_counter()
    runner.run_mcat(max_steps=MAX_STEPS)
    wall_ms = (time.perf_counter() - started) * 1000.0
    outcome = _run_outcome(runner)
    outcome["wall_ms"] = wall_ms
    outcome["rate"] = outcome["codelets"] / wall_ms * 1000.0 if wall_ms else 0.0
    return outcome


class _Accumulator:
    """Inclusive wall time and call count for one wrapped method."""

    __slots__ = ("seconds", "calls")

    def __init__(self) -> None:
        self.seconds = 0.0
        self.calls = 0


def _wrap_timed(cls: type, name: str, acc: _Accumulator) -> None:
    original = getattr(cls, name)
    perf_counter = time.perf_counter

    def timed(*args: Any, **kwargs: Any) -> Any:
        started = perf_counter()
        try:
            return original(*args, **kwargs)
        finally:
            acc.seconds += perf_counter() - started
            acc.calls += 1

    setattr(cls, name, timed)


def task_phases(problem: dict[str, Any]) -> dict[str, Any]:
    """One instrumented run, reporting inclusive time per phase.

    The wrappers are installed on the classes in this worker process only, and the
    process is discarded afterwards, so nothing under ``server/engine/`` needs an
    instrumentation hook of its own.

    They are installed *after* ``init_mcat``, so the profile covers the run and not the
    setup.  Initialisation posts ``2 x num_objects`` codelets — 24 on the profile
    problem — and charging those to ``coderack.post`` would put work in the profile that
    the timed region does not contain.
    """
    runner = _fresh_runner(problem)

    accumulators: dict[str, _Accumulator] = {}
    for phase in PHASES:
        module_name, class_name, method_name = phase["target"]
        cls = getattr(importlib.import_module(module_name), class_name)
        acc = _Accumulator()
        accumulators[phase["key"]] = acc
        _wrap_timed(cls, method_name, acc)

    started = time.perf_counter()
    runner.run_mcat(max_steps=MAX_STEPS)
    total_ms = (time.perf_counter() - started) * 1000.0

    outcome = _run_outcome(runner)
    outcome["total_ms"] = total_ms
    outcome["phases"] = {
        key: {"ms": acc.seconds * 1000.0, "calls": acc.calls}
        for key, acc in accumulators.items()
    }
    return outcome


def task_counters(problem: dict[str, Any]) -> dict[str, Any]:
    """One counter-instrumented run: coderack occupancy, evictions, bin lookups.

    Occupancy is sampled on entry to ``post``, before any eviction, so "at capacity"
    means what ``post`` itself means by it.  These counts are deterministic for a fixed
    seed, so a single run is the whole measurement rather than a sample of it.

    As in ``task_phases``, counting starts after ``init_mcat`` so that the initial
    codelets are not counted as posts the run made.
    """
    from server.engine.coderack import Coderack

    occupancy: list[int] = []
    counts = {"posts": 0, "posts_at_capacity": 0, "evictions": 0,
              "urgency_to_bin_calls": 0, "remove_old_calls": 0}

    runner = _fresh_runner(problem)

    original_post = Coderack.post
    original_remove = Coderack.remove_old_codelets
    original_bin = Coderack._urgency_to_bin

    def post(self: Any, codelet: Any, current_time: Any = None, rng: Any = None) -> Any:
        counts["posts"] += 1
        occupancy.append(self._total_count)
        if self._total_count >= self.max_size:
            counts["posts_at_capacity"] += 1
        return original_post(self, codelet, current_time, rng)

    def remove_old_codelets(self: Any, current_time: int, num_to_remove: int,
                            rng: Any) -> Any:
        counts["remove_old_calls"] += 1
        removed = original_remove(self, current_time, num_to_remove, rng)
        counts["evictions"] += len(removed)
        return removed

    def urgency_to_bin(self: Any, urgency: int) -> int:
        counts["urgency_to_bin_calls"] += 1
        return original_bin(self, urgency)

    Coderack.post = post
    Coderack.remove_old_codelets = remove_old_codelets
    Coderack._urgency_to_bin = urgency_to_bin

    runner.run_mcat(max_steps=MAX_STEPS)

    outcome = _run_outcome(runner)
    outcome.update(counts)
    outcome["max_size"] = runner.ctx.coderack.max_size
    outcome["occupancy"] = {
        "median": statistics.median(occupancy) if occupancy else 0,
        "mean": statistics.fmean(occupancy) if occupancy else 0.0,
        "min": min(occupancy) if occupancy else 0,
        "max": max(occupancy) if occupancy else 0,
    }
    posts = counts["posts"] or 1
    outcome["posts_at_capacity_pct"] = counts["posts_at_capacity"] / posts * 100.0
    # The quantity WP1.1 promises to cut: inspections per codelet evicted.
    outcome["bin_lookups_per_eviction"] = (
        counts["urgency_to_bin_calls"] / counts["evictions"]
        if counts["evictions"] else 0.0
    )
    return outcome


class SnapshotUnavailable(RuntimeError):
    """The pure serializers could not be imported, so the section cannot run."""


SERIALIZER_NAMES = (
    "rng", "workspace", "slipnet", "coderack", "themespace", "trace", "runner",
)


def _load_serializers() -> tuple[dict[str, Callable], str, list[str]]:
    """Return ``{component: serialize_fn}``, the import route taken, and any notes.

    One route, because since WP3.1 there is only one: the serializers are engine code
    and import nothing but the standard library and ``server.engine``.  A failure here
    means something is genuinely wrong rather than merely absent, so it is reported as
    a skip reason instead of being worked around.
    """
    try:
        module = importlib.import_module("server.engine.serialization")
        serializers = {
            n: getattr(module, f"serialize_{n}_state") for n in SERIALIZER_NAMES
        }
    except (ImportError, AttributeError) as exc:
        raise SnapshotUnavailable(
            f"could not import the serializers from server.engine.serialization ({exc})"
        ) from exc
    return serializers, "server.engine.serialization", []


def task_snapshot(problem: dict[str, Any]) -> dict[str, Any]:
    """Serialise engine state at every update cycle, as ``run_service`` would.

    The ``serialize_*`` calls and the JSON encoding of their result are timed
    separately, because they are charged to different places: the serializers run in
    ``save_cycle_snapshot`` and the encoding runs inside the database driver as it
    prepares the JSONB parameter.  Both are CPU cost of the same process, so the sum is
    what a snapshot costs and the two parts say where it goes.  The plan's 0.37-0.46 ms
    corresponds to the sum.
    """
    try:
        serializers, route, notes = _load_serializers()
    except SnapshotUnavailable as exc:
        return {"available": False, "reason": str(exc)}

    from server.engine.runner import (
        STATUS_ANSWER_FOUND, STATUS_HALTED, STATUS_RUNNING,
    )

    runner = _fresh_runner(problem)
    ctx = runner.ctx
    ucl = ctx.meta.get_param("update_cycle_length", 15)

    serialize_ms: list[float] = []
    encode_ms: list[float] = []
    total_bytes: list[int] = []
    component_bytes: dict[str, list[int]] = {name: [] for name in SERIALIZER_NAMES}

    runner.status = STATUS_RUNNING
    steps = 0
    while runner.status == STATUS_RUNNING:
        if steps >= MAX_STEPS:
            runner.status = STATUS_HALTED
            break
        result = runner.step_mcat()
        steps += 1
        if result.answer_found:
            runner.status = STATUS_ANSWER_FOUND
        if ctx.codelet_count % ucl != 0:
            continue

        started = time.perf_counter()
        state = {name: fn(ctx) for name, fn in serializers.items()}
        serialize_ms.append((time.perf_counter() - started) * 1000.0)

        started = time.perf_counter()
        encoded = {name: json.dumps(value, default=str) for name, value in state.items()}
        encode_ms.append((time.perf_counter() - started) * 1000.0)

        snapshot_size = 0
        for name, text in encoded.items():
            component_bytes[name].append(len(text))
            snapshot_size += len(text)
        total_bytes.append(snapshot_size)

    outcome = _run_outcome(runner)
    median_total = statistics.median(total_bytes) if total_bytes else 0
    combined_ms = [s + e for s, e in zip(serialize_ms, encode_ms)]
    outcome.update({
        "available": True,
        "import_route": route,
        "notes": notes,
        "snapshots": len(total_bytes),
        "serialize_ms": {
            "median": statistics.median(serialize_ms) if serialize_ms else 0.0,
            "min": min(serialize_ms) if serialize_ms else 0.0,
            "max": max(serialize_ms) if serialize_ms else 0.0,
        },
        "combined_ms": {
            "median": statistics.median(combined_ms) if combined_ms else 0.0,
            "min": min(combined_ms) if combined_ms else 0.0,
            "max": max(combined_ms) if combined_ms else 0.0,
        },
        "json_encode_ms_median": statistics.median(encode_ms) if encode_ms else 0.0,
        "bytes": {
            "median": median_total,
            "min": min(total_bytes) if total_bytes else 0,
            "max": max(total_bytes) if total_bytes else 0,
        },
        "components": {
            name: {
                "median_bytes": statistics.median(values) if values else 0,
                "pct": (statistics.median(values) / median_total * 100.0)
                       if values and median_total else 0.0,
            }
            for name, values in component_bytes.items()
        },
        "total_serialize_ms": sum(serialize_ms),
        "total_combined_ms": sum(combined_ms),
    })
    return outcome


# ──────────────────────────────────────────────────────────────────────────────
# Driver side
# ──────────────────────────────────────────────────────────────────────────────

def run_isolated(task: Callable, argument: Any) -> Any:
    """Run one task in a brand-new interpreter and return its result.

    ``max_tasks_per_child=1`` with the ``spawn`` context is what makes each measurement
    a first-run-in-process measurement; ``max_workers=1`` keeps tasks serial, since
    overlapping them would have them competing for the same cores they are timing.
    """
    context = multiprocessing.get_context("spawn")
    with ProcessPoolExecutor(
        max_workers=1, max_tasks_per_child=1, mp_context=context
    ) as executor:
        return executor.submit(task, argument).result()


def summarise(samples: list[float]) -> dict[str, float]:
    """Summarise repeats.  ``best`` is the reported figure; the rest describe the noise."""
    return {
        "best": min(samples),
        "median": statistics.median(samples),
        "min": min(samples),
        "max": max(samples),
        "spread_pct": (max(samples) - min(samples)) / min(samples) * 100.0
                      if min(samples) else 0.0,
        "samples": list(samples),
    }


def git_info() -> dict[str, Any]:
    def git(*args: str) -> str:
        return subprocess.run(
            ["git", *args], cwd=REPO, capture_output=True, text=True, timeout=10
        ).stdout.strip()

    try:
        return {
            "commit": git("rev-parse", "HEAD"),
            "short": git("rev-parse", "--short", "HEAD"),
            "dirty": bool(git("status", "--porcelain")),
        }
    except Exception:  # pragma: no cover - git may be absent
        return {"commit": None, "short": None, "dirty": None}


def environment_info() -> dict[str, Any]:
    return {
        "python": platform.python_version(),
        "implementation": platform.python_implementation(),
        "machine": platform.machine(),
        "platform": platform.platform(),
        "cpu_count": os.cpu_count(),
    }


def load_average() -> list[float] | None:
    try:
        return [round(v, 2) for v in os.getloadavg()]
    except (OSError, AttributeError):  # pragma: no cover - not all platforms have it
        return None


# ── measurement passes ────────────────────────────────────────────────────────

def measure_throughput(problems: list[dict], repeats: int, say: Callable) -> list[dict]:
    results = []
    for problem in problems:
        runs = [run_isolated(task_throughput, problem) for _ in range(repeats)]
        codelet_counts = {r["codelets"] for r in runs}
        record = {
            "problem": {k: problem[k] for k in ("initial", "modified", "target", "seed")},
            "label": problem["label"],
            "status": runs[0]["status"],
            "answer": runs[0]["answer"],
            "codelets": runs[0]["codelets"],
            "codelets_stable": len(codelet_counts) == 1,
            "trace_events": runs[0]["trace_events"],
            "update_cycles": runs[0]["update_cycles"],
            "wall_ms": summarise([r["wall_ms"] for r in runs]),
            "rate": summarise([r["rate"] for r in runs]),
        }
        if not record["codelets_stable"]:
            record["codelet_counts_observed"] = sorted(codelet_counts)
        results.append(record)
        say(f"    {problem['label']}: {record['codelets']} codelets, "
            f"{record['wall_ms']['best']:.1f} ms best of {repeats} "
            f"(spread {record['wall_ms']['spread_pct']:.0f}%)")
    return results


def measure_phases(problem: dict, repeats: int, say: Callable) -> dict:
    runs = [run_isolated(task_phases, problem) for _ in range(repeats)]

    # The whole table comes from one repeat — the fastest — so that the rows describe a
    # single coherent run.  Taking each row's own minimum would mix repeats and could
    # produce a breakdown that does not add up.
    best = min(runs, key=lambda r: r["total_ms"])
    total = summarise([r["total_ms"] for r in runs])
    say(f"    {problem['label']}: {runs[0]['codelets']} codelets, "
        f"{total['best']:.1f} ms instrumented, best of {repeats} "
        f"(spread {total['spread_pct']:.0f}%)")

    phases = {}
    for phase in PHASES:
        key = phase["key"]
        samples = [r["phases"][key]["ms"] for r in runs]
        phases[key] = {
            "label": phase["label"],
            "group": phase["group"],
            "nested_in": phase.get("nested_in"),
            "plan_ms": phase["plan_ms"],
            "calls": best["phases"][key]["calls"],
            "best_ms": best["phases"][key]["ms"],
            "ms": summarise(samples),
            "pct_of_run": best["phases"][key]["ms"] / best["total_ms"] * 100.0,
        }

    numeric_total = sum(
        phases[p["key"]]["best_ms"] for p in PHASES if p["group"] == "numeric"
    )
    codelet_ms = phases["codelet_execution"]["best_ms"]
    fraction_codelets = codelet_ms / best["total_ms"]
    fraction_both = (codelet_ms + numeric_total) / best["total_ms"]

    return {
        "problem": {k: problem[k] for k in ("initial", "modified", "target", "seed")},
        "label": problem["label"],
        "codelets": runs[0]["codelets"],
        "update_cycles": runs[0]["update_cycles"],
        "total_ms": total,
        "plan_total_ms": PLAN_PROFILE_TOTAL_MS,
        "phases": phases,
        "numeric_substrate_ms": numeric_total,
        "numeric_substrate_pct": numeric_total / best["total_ms"] * 100.0,
        "amdahl": {
            "codelets_only": {
                "fraction": fraction_codelets,
                "ceiling": 1.0 / (1.0 - fraction_codelets),
                "plan_fraction": 0.275,
                "plan_ceiling": 1.38,
            },
            "codelets_and_numeric": {
                "fraction": fraction_both,
                "ceiling": 1.0 / (1.0 - fraction_both),
                "plan_fraction": 0.483,
                "plan_ceiling": 1.94,
            },
        },
    }


def measure_counters(problem: dict, say: Callable) -> dict:
    record = run_isolated(task_counters, problem)
    say(f"    {problem['label']}: {record['posts']:,} posts, "
        f"{record['evictions']:,} evictions")
    record["label"] = problem["label"]
    record["plan"] = PLAN_OCCUPANCY
    return record


def measure_snapshot(problem: dict, repeats: int, say: Callable) -> dict:
    runs = [run_isolated(task_snapshot, problem) for _ in range(repeats)]
    if not runs[0].get("available"):
        say(f"    skipped: {runs[0]['reason']}")
        return runs[0]

    # Sizes are deterministic, so any repeat gives the same bytes; the timings are not,
    # so they come from the least-disturbed repeat.
    first = min(runs, key=lambda r: r["combined_ms"]["median"])
    record = {
        "available": True,
        "label": problem["label"],
        "import_route": first["import_route"],
        "notes": first["notes"],
        "snapshots": first["snapshots"],
        "bytes": first["bytes"],
        "components": first["components"],
        "serialize_ms": summarise([r["serialize_ms"]["median"] for r in runs]),
        "serialize_ms_within_run": first["serialize_ms"],
        "json_encode_ms": summarise([r["json_encode_ms_median"] for r in runs]),
        "combined_ms": summarise([r["combined_ms"]["median"] for r in runs]),
        "combined_ms_within_run": first["combined_ms"],
        "total_serialize_ms": summarise([r["total_serialize_ms"] for r in runs]),
        "total_combined_ms": summarise([r["total_combined_ms"] for r in runs]),
        "plan": PLAN_SNAPSHOT,
    }
    say(f"    {record['snapshots']} snapshots, {record['bytes']['median']:,.0f} bytes, "
        f"{record['combined_ms']['best']:.2f} ms each")
    return record


# ── reporting ─────────────────────────────────────────────────────────────────

def _delta(measured: float, reference: float | None) -> str:
    if reference in (None, 0):
        return ""
    return f"{(measured - reference) / reference * 100:+6.0f}%"


def _range(summary: dict[str, float], digits: int = 1) -> str:
    """The observed range across repeats — how noisy the machine was while measuring."""
    if summary["min"] == summary["max"]:
        return ""
    return f"[{summary['min']:.{digits}f}-{summary['max']:.{digits}f}]"


def report_throughput(results: list[dict], reference: dict | None, out: Callable) -> None:
    out("")
    out("1. Throughput — no instrumentation installed, best repeat")
    out("")
    out(f"   {'Problem':<30}{'Codelets':>9}{'Wall ms':>10}{'  ':<16}"
        f"{'Rate /s':>10}{'ref /s':>10}{'delta':>8}")
    for record in results:
        plan = PLAN_THROUGHPUT.get(_plan_key(record["problem"]))
        if reference:
            match = next(
                (r for r in reference.get("throughput", [])
                 if r["label"] == record["label"]), None
            )
            plan = None
            if match:
                plan = {"rate": match["rate"]["best"], "codelets": match["codelets"]}
        wall = record["wall_ms"]
        rate = record["rate"]
        reference_rate = f"{plan['rate']:,.0f}" if plan else "-"
        out(f"   {record['label']:<30}{record['codelets']:>9}"
            f"{wall['best']:>10.1f}  {_range(wall):<16}"
            f"{rate['max']:>10,.0f}{reference_rate:>10}"
            f"{_delta(rate['max'], plan['rate'] if plan else None):>8}")
    out("")
    for record in results:
        plan = PLAN_THROUGHPUT.get(_plan_key(record["problem"]))
        if plan and plan["codelets"] != record["codelets"]:
            out(f"   NOTE  {record['label']}: {record['codelets']} codelets, "
                f"reference {plan['codelets']} — the run itself has changed, so the "
                f"rate is not comparable.")
        if not record["codelets_stable"]:
            out(f"   WARN  {record['label']}: codelet count varied across repeats "
                f"({record['codelet_counts_observed']}) — the engine is not "
                f"deterministic for this seed.")
    out("   Reference column: Phase 0 plan section A1 'Measured cost'.")


def report_phases(profile: dict, reference: dict | None, out: Callable) -> None:
    total = profile["total_ms"]
    out("")
    out(f"2. Per-phase profile — instrumented, fastest repeat: {profile['label']}")
    out(f"   {profile['codelets']} codelets, {profile['update_cycles']} update cycles, "
        f"{total['best']:.1f} ms {_range(total)} instrumented "
        f"(reference {profile['plan_total_ms']:.0f} ms)")
    out("")
    out(f"   {'Phase':<38}{'ms':>8}{'  ':<16}{'% run':>8}{'calls':>9}"
        f"{'ref ms':>9}{'ref %':>8}")

    reference_profile = (reference or {}).get("profile", {})
    ref_phases = reference_profile.get("phases", {})
    ref_total = reference_profile.get("total_ms", {}).get("best")
    for phase in PHASES:
        key = phase["key"]
        row = profile["phases"][key]
        if row["group"] == "extra":
            continue
        label = ("  └ " + row["label"]) if row["nested_in"] else row["label"]
        plan_ms = row["plan_ms"]
        denominator = profile["plan_total_ms"]
        if reference and key in ref_phases:
            plan_ms = ref_phases[key]["best_ms"]
            denominator = ref_total or denominator
        plan_pct = plan_ms / denominator * 100.0 if plan_ms is not None else None
        reference_ms = f"{plan_ms:.1f}" if plan_ms is not None else "-"
        reference_pct = f"{plan_pct:.1f}%" if plan_pct is not None else "-"
        out(f"   {label:<38}{row['best_ms']:>8.1f}  {_range(row['ms']):<16}"
            f"{row['pct_of_run']:>7.1f}%{row['calls']:>9,}"
            f"{reference_ms:>9}{reference_pct:>8}")

    plan_numeric = sum(
        p["plan_ms"] for p in PHASES if p["group"] == "numeric" and p["plan_ms"]
    )
    numeric_denominator = profile["plan_total_ms"]
    if reference and "numeric_substrate_ms" in reference_profile:
        plan_numeric = reference_profile["numeric_substrate_ms"]
        numeric_denominator = ref_total or numeric_denominator
    out(f"   {'[numeric substrate total]':<38}{profile['numeric_substrate_ms']:>8.1f}"
        f"  {'':<16}{profile['numeric_substrate_pct']:>7.1f}%{'':>9}"
        f"{plan_numeric:>9.1f}"
        f"{plan_numeric / numeric_denominator * 100:>7.1f}%")
    out("")
    out("   Timings are inclusive and the rows overlap: remove_old_codelets is inside")
    out("   coderack.post, both posting rows call coderack.post, and codelet execution")
    out("   calls it too whenever a codelet posts a codelet. Only the four numeric rows")
    out("   are disjoint, which is why they alone are summed.")
    out("")
    out("   Numeric work absent from the reference table (excluded from the total above):")
    for phase in PHASES:
        if phase["group"] != "extra":
            continue
        row = profile["phases"][phase["key"]]
        out(f"   {row['label']:<38}{row['best_ms']:>8.1f}  {_range(row['ms']):<16}"
            f"{row['pct_of_run']:>7.1f}%{row['calls']:>9,}")

    out("")
    out("3. Amdahl fractions and ceilings")
    out("")
    out(f"   {'Parallelising':<38}{'fraction':>10}{'ceiling':>10}"
        f"{'ref frac':>10}{'ref ceil':>10}")
    for key, label in (
        ("codelets_only", "codelet execution only"),
        ("codelets_and_numeric", "codelets + numeric substrate"),
    ):
        row = profile["amdahl"][key]
        plan_fraction, plan_ceiling = row["plan_fraction"], row["plan_ceiling"]
        ref_row = reference_profile.get("amdahl", {}).get(key)
        if ref_row:
            plan_fraction, plan_ceiling = ref_row["fraction"], ref_row["ceiling"]
        out(f"   {label:<38}{row['fraction'] * 100:>9.1f}%{row['ceiling']:>9.2f}x"
            f"{plan_fraction * 100:>9.1f}%{plan_ceiling:>9.2f}x")
    out("")
    out("   Codelet execution includes the coderack.post calls made by codelets, so the")
    out("   fractions are marginally optimistic; the ceilings are upper bounds already.")


def report_counters(counters: dict, out: Callable) -> None:
    plan = counters["plan"]
    occupancy = counters["occupancy"]
    out("")
    out(f"4. Coderack occupancy — counter-instrumented: {counters['label']}")
    out("")
    out(f"   {'Posts':<38}{counters['posts']:>12,}")
    out(f"   {'Posts made at capacity':<38}{counters['posts_at_capacity']:>12,}"
        f"   {counters['posts_at_capacity_pct']:.1f}%  "
        f"(reference {plan['posts_at_capacity_pct']:.0f}%)")
    out(f"   {'Occupancy at post: median':<38}{occupancy['median']:>12,.0f}"
        f"   of {counters['max_size']}  (reference {plan['median_occupancy']})")
    out(f"   {'Occupancy at post: mean':<38}{occupancy['mean']:>12.1f}")
    extremes = f"{occupancy['min']} / {occupancy['max']}"
    out(f"   {'Occupancy at post: min / max':<38}{extremes:>12}")
    out(f"   {'remove_old_codelets calls':<38}{counters['remove_old_calls']:>12,}")
    out(f"   {'Codelets evicted':<38}{counters['evictions']:>12,}"
        f"   (reference {plan['evictions']:,})")
    out(f"   {'_urgency_to_bin calls':<38}{counters['urgency_to_bin_calls']:>12,}"
        f"   (reference {plan['urgency_to_bin_calls']:,})")
    out(f"   {'_urgency_to_bin calls per eviction':<38}"
        f"{counters['bin_lookups_per_eviction']:>12.1f}")
    out("")
    out("   These are the numbers WP1.1 is judged against: incremental eviction should")
    out("   collapse the last two rows while leaving the first three unchanged, since")
    out("   it must preserve the selection distribution exactly.")


def report_snapshot(snapshot: dict, out: Callable) -> None:
    out("")
    out("5. Snapshot size and serialisation cost")
    out("")
    if not snapshot.get("available"):
        out(f"   SKIPPED — {snapshot['reason']}")
        out("   This section needs the pure serialize_* functions to be importable")
        out("   from server/engine/serialization.py, which depends on nothing but the")
        out("   standard library and the engine — so a skip here is a real breakage.")
        return

    out(f"   imported from: {snapshot['import_route']}")
    for note in snapshot["notes"]:
        out(f"   note: {note}")
    plan = snapshot["plan"]
    serialize = snapshot["serialize_ms"]
    combined = snapshot["combined_ms"]
    within = snapshot["combined_ms_within_run"]
    size = snapshot["bytes"]
    out("")
    out(f"   {'Snapshots taken':<38}{snapshot['snapshots']:>12,}")
    out(f"   {'Bytes per snapshot (median)':<38}{size['median']:>12,.0f}"
        f"   {size['median'] / 1024:.1f} KB  (reference ~{plan['bytes'] / 1024:.0f} KB)")
    extremes = f"{size['min']:,} / {size['max']:,}"
    out(f"   {'Bytes per snapshot (min / max)':<38}{extremes:>12}")
    out(f"   {'serialize_* calls (median snapshot)':<38}{serialize['best']:>12.2f} ms")
    out(f"   {'json.dumps of the result':<38}"
        f"{snapshot['json_encode_ms']['best']:>12.2f} ms")
    out(f"   {'both, per snapshot':<38}{combined['best']:>12.2f} ms"
        f"   within one run {within['min']:.2f}-{within['max']:.2f} ms"
        f"  (reference {plan['serialize_ms_low']}-{plan['serialize_ms_high']} ms)")
    out(f"   {'Whole-run cost of snapshotting':<38}"
        f"{snapshot['total_combined_ms']['best']:>12.1f} ms"
        f"   of which serialising "
        f"{snapshot['total_serialize_ms']['best']:.1f} ms")
    out("")
    out(f"   {'Component':<38}{'bytes':>12}{'share':>9}{'reference':>11}")
    ordered = sorted(
        snapshot["components"].items(), key=lambda kv: -kv[1]["median_bytes"]
    )
    for name, component in ordered:
        reference = plan["components_pct"].get(name)
        out(f"   {name:<38}{component['median_bytes']:>12,.0f}"
            f"{component['pct']:>8.1f}%"
            f"{(f'{reference:.0f}%' if reference is not None else '-'):>11}")


# ── main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Benchmark the Petacat engine (Phase 0, WP0.4).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="A problem spec is initial:modified:target@seed, e.g. abc:abd:mrrjjj@42.",
    )
    parser.add_argument(
        "--problems", default=",".join(DEFAULT_PROBLEMS),
        help="comma-separated problem specs for the throughput section "
             "(default: the plan's five reference problems)",
    )
    parser.add_argument(
        "--profile-problem", default=DEFAULT_PROFILE_PROBLEM,
        help="problem to profile, count and snapshot (default: %(default)s)",
    )
    parser.add_argument(
        "--repeats", type=int, default=5,
        help="runs per measurement, each in a fresh interpreter (default: %(default)s)",
    )
    parser.add_argument(
        "--sections", default=",".join(SECTIONS),
        help=f"comma-separated subset of {','.join(SECTIONS)} (default: all)",
    )
    parser.add_argument("--json", dest="json_path", default=None,
                        help="write the machine-readable record here")
    parser.add_argument("--baseline", default=None,
                        help="a previous --json record to compare against instead of "
                             "the plan's published figures")
    parser.add_argument("--quiet", action="store_true",
                        help="suppress the human-readable report")
    args = parser.parse_args()

    if args.repeats < 1:
        parser.error("--repeats must be at least 1")
    sections = [s.strip() for s in args.sections.split(",") if s.strip()]
    unknown = [s for s in sections if s not in SECTIONS]
    if unknown:
        parser.error(f"unknown section(s): {', '.join(unknown)}")
    if args.quiet and not args.json_path:
        print("bench_engine: --quiet without --json produces no output at all",
              file=sys.stderr)

    try:
        problems = [parse_problem(s) for s in args.problems.split(",") if s.strip()]
        profile_problem = parse_problem(args.profile_problem)
    except argparse.ArgumentTypeError as exc:
        parser.error(str(exc))
    if not problems:
        parser.error("--problems is empty")

    reference = None
    if args.baseline:
        with open(args.baseline) as handle:
            reference = json.load(handle)

    lines: list[str] = []

    def out(text: str = "") -> None:
        lines.append(text)

    def say(text: str) -> None:
        if not args.quiet:
            print(text, flush=True)

    def warn(text: str) -> None:
        """Warnings go to stderr even under --quiet: they qualify the numbers."""
        print(text, file=sys.stderr, flush=True)

    git = git_info()
    environment = environment_info()
    started_at = datetime.now(timezone.utc)
    load_before = load_average()

    say(f"Petacat engine benchmark — commit {git['short'] or '?'}"
        f"{' (working tree dirty)' if git['dirty'] else ''}, "
        f"Python {environment['python']} on {environment['machine']}, "
        f"{args.repeats} repeat(s) per measurement, one fresh interpreter each")

    cpus = environment["cpu_count"] or 1
    if load_before and load_before[0] > cpus * 0.5:
        warn(f"WARNING  load average {load_before[0]} on {cpus} cores — other work on "
             f"this machine will inflate every timing. The reported figures are the "
             f"fastest repeat, which limits the damage, but a quiet machine or more "
             f"--repeats is better.")

    record: dict[str, Any] = {
        "generated_by": "scripts/bench_engine.py",
        "timestamp": started_at.isoformat(),
        "git": git,
        "environment": environment,
        "load_average_start": load_before,
        "config": {
            "repeats": args.repeats,
            "sections": sections,
            "problems": [p["label"] for p in problems],
            "profile_problem": profile_problem["label"],
            "max_steps": MAX_STEPS,
            "baseline": args.baseline,
        },
    }

    if "throughput" in sections:
        say("\n[throughput] uninstrumented runs")
        record["throughput"] = measure_throughput(problems, args.repeats, say)
        report_throughput(record["throughput"], reference, out)

    if "phases" in sections:
        say("\n[phases] instrumented runs")
        record["profile"] = measure_phases(profile_problem, args.repeats, say)
        report_phases(record["profile"], reference, out)

    if "counters" in sections:
        say("\n[counters] one counter-instrumented run")
        record["counters"] = measure_counters(profile_problem, say)
        report_counters(record["counters"], out)

    if "snapshot" in sections:
        say("\n[snapshot] serialisation cost")
        record["snapshot"] = measure_snapshot(profile_problem, args.repeats, say)
        report_snapshot(record["snapshot"], out)

    record["load_average_end"] = load_average()
    record["elapsed_seconds"] = round(
        (datetime.now(timezone.utc) - started_at).total_seconds(), 1
    )

    if not args.quiet:
        print("\n".join(lines))
        print()

    if args.json_path:
        directory = os.path.dirname(os.path.abspath(args.json_path))
        if directory:
            os.makedirs(directory, exist_ok=True)
        with open(args.json_path, "w") as handle:
            json.dump(record, handle, indent=2)
            handle.write("\n")
        say(f"Wrote {args.json_path}")


if __name__ == "__main__":
    main()
