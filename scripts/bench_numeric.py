#!/usr/bin/env python3
"""Benchmark the numeric substrate — the scaling curve behind Phase 0 WP4.5.

Why this is a companion to ``bench_engine.py`` rather than a section inside it
--------------------------------------------------------------------------------
``bench_engine.py`` measures *a run*: codelets per second, where the time goes,
how full the coderack is, what a snapshot costs.  Every one of its conventions is
right for that and wrong for this.

* It runs each repeat **in a fresh interpreter**, which is exactly right when the
  quantity of interest is a whole run and allocator state is a confound.  It is
  exactly wrong for a kernel measurement: ``mx.fast.metal_kernel`` JIT-compiles
  Metal on first call, so a fresh interpreter per repeat would measure the
  compiler.  Here the kernel is warmed and then timed, which is the standard
  practice for the thing being measured.

* It has **no third-party dependency at all**, deliberately, so that the engine's
  profile can be taken on any checkout.  The scaling curve cannot be taken without
  NumPy and MLX, and pulling them into the engine profiler to serve one section
  would give the profiler a dependency it does not otherwise need.

* Its unit is a *problem*.  The unit here is a *Slipnet size*, and three of the
  four sizes measured have no problem attached to them — they are synthetic
  graphs standing in for a Slipnet that does not exist yet.

The two scripts share the conventions that matter: fastest-of-N with the observed
range printed beside it, a JSON record, ``--baseline`` comparison, and the load
average recorded so a reader can tell a busy machine from a slow one.  The
reasoning for fastest-rather-than-median is given at length in ``bench_engine.py``
and applies here unchanged.

What is measured
----------------
``scaling``
    One decay → spread → flush update cycle over a synthetic Slipnet, at each
    requested size, on each available backend.  Two timings per cell:

    *device* — the update alone, with the state resident.  This is the kernel
    timing the plan asks for, and it is what a Slipnet with no Python object graph
    behind it would pay.

    *round-trip* — load, update, resolve the jump candidates, apply the jumps,
    store.  This is what today's engine pays, because the object graph is still
    the authority for activation and because the probabilistic jump consumes the
    host's RNG.  The gap between the two columns is the cost of the object graph,
    and it is the reason the layout in ``engine/numeric/layout.py`` is built to
    become the primary representation rather than a derived one.

``engine``
    Whole runs of the profile problem under each backend, so that "did the 59-node
    engine get slower" is answerable from the same command that produces the
    scaling curve.  Reports codelets per second and the answer reached — the
    latter because the float32 backend is *expected* to reach different answers on
    some seeds, and a benchmark that hid that would be hiding the most important
    thing it knows.

Usage
-----
    .venv/bin/python scripts/bench_numeric.py [--sizes 59,1000,10000,100000]
                                              [--backends python,numpy,mlx,...]
                                              [--cycles N] [--repeats N]
                                              [--sections scaling,engine]
                                              [--json PATH] [--baseline PATH]
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import statistics
import sys
import time
from datetime import datetime, timezone
from typing import Any, Callable

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

SEED_DIR = os.path.join(REPO, "seed_data")

SECTIONS = ("scaling", "engine")

#: The four sizes Phase 0 WP4.5 names.  59 is today's Slipnet; 10⁵ is within half
#: an order of magnitude of the ~300,000 nodes later phases target, which is close
#: enough that the trend between 10⁴ and 10⁵ extrapolates honestly and far enough
#: that the measurement finishes in seconds rather than minutes.
DEFAULT_SIZES = (59, 1_000, 10_000, 100_000)

#: Update cycles timed per repeat.  The state evolves across them exactly as it
#: would in a run, so this is not the same cycle measured N times — it is N
#: consecutive cycles, which is what keeps the activation distribution realistic
#: rather than frozen at its initial value.
DEFAULT_CYCLES = 20

DEFAULT_REPEATS = 5

#: The profile problem from Phase 0 section B2, so the engine section is directly
#: comparable with ``bench_engine.py``'s output.
PROFILE_PROBLEM = {"initial": "abc", "modified": "abd", "target": "mrrjjj", "seed": 42}

MAX_STEPS = 6000


# ──────────────────────────────────────────────────────────────────────────────
# Measurement
# ──────────────────────────────────────────────────────────────────────────────


def _backend_variants(names: list[str]) -> list[tuple[str, Callable[[], Any]]]:
    """``(label, factory)`` for each requested backend, plus the MLX control.

    ``mlx-composed`` is the GPU backend with the hand-written kernel switched off,
    running the same computation in composed MLX operations.  It is measured
    because "the custom kernel is worth writing" is a claim, and this is the
    control that tests it.
    """
    from server.engine.numeric.backend import get_backend

    variants: list[tuple[str, Callable[[], Any]]] = []
    for name in names:
        variants.append((name, (lambda n=name: get_backend(n))))
        if name == "mlx":
            from server.engine.numeric.mlx_backend import MlxBackend

            variants.append(("mlx-composed", lambda: MlxBackend(use_kernel=False)))
    return variants


def measure_scaling(
    sizes: list[int],
    backend_names: list[str],
    cycles: int,
    repeats: int,
    say: Callable[[str], None],
) -> list[dict[str, Any]]:
    from server.engine.numeric.synthetic import (
        REAL_LINKS_PER_NODE,
        synthetic_state,
        synthetic_topology,
    )

    variants = _backend_variants(backend_names)
    rows: list[dict[str, Any]] = []

    for n_nodes in sizes:
        say(f"  building a synthetic Slipnet of {n_nodes:,} nodes")
        topology = synthetic_topology(n_nodes, seed=n_nodes)
        state = synthetic_state(topology, seed=n_nodes + 1)
        row: dict[str, Any] = {
            "nodes": n_nodes,
            "edges": topology.n_edges,
            "links_per_node": topology.n_edges / max(1, n_nodes),
            "backends": {},
        }
        for label, factory in variants:
            say(f"    {label} at {n_nodes:,} nodes")
            try:
                backend = factory()
            except Exception as exc:  # pragma: no cover - depends on the machine
                row["backends"][label] = {"unavailable": str(exc)}
                continue
            row["backends"][label] = _time_one_cell(
                backend, topology, state, cycles, repeats
            )
        row["reference_links_per_node"] = REAL_LINKS_PER_NODE
        rows.append(row)
    return rows


def _time_one_cell(
    backend: Any, topology: Any, state: Any, cycles: int, repeats: int
) -> dict[str, Any]:
    """Device-only and round-trip timings for one (backend, size) cell."""
    session = backend.open_slipnet(topology)

    # Warm-up: compiles the Metal kernel, faults in the arrays, and — for the
    # composed MLX path — builds and caches the operation graph.  Not timed, and
    # not optional: on the GPU the first call is two orders of magnitude slower
    # than the second.
    session.load(state)
    for _ in range(3):
        session.update(100.0, 1.0)
        session.jump_candidates()

    device_samples: list[float] = []
    for _ in range(repeats):
        session.load(state)
        started = time.perf_counter()
        for _ in range(cycles):
            session.update(100.0, 1.0)
        device_samples.append((time.perf_counter() - started) / cycles * 1000.0)

    round_trip_samples: list[float] = []
    for _ in range(repeats):
        started = time.perf_counter()
        for _ in range(cycles):
            session.load(state)
            session.update(100.0, 1.0)
            indices, probabilities = session.jump_candidates()
            session.apply_jumps(indices[::7])
            session.store()
        round_trip_samples.append((time.perf_counter() - started) / cycles * 1000.0)

    return {
        "device_ms": summarise(device_samples),
        "round_trip_ms": summarise(round_trip_samples),
    }


def measure_engine(
    backend_names: list[str], repeats: int, say: Callable[[str], None]
) -> dict[str, Any]:
    """Whole runs of the profile problem under each backend.

    Run in this interpreter rather than in a fresh one per repeat.  That differs
    from ``bench_engine.py`` and the reason is the same one that shapes the rest
    of this script: an MLX backend pays its Metal compilation on first use, and a
    fresh interpreter per repeat would charge every repeat for it.  The
    consequence is that these absolute numbers are *not* directly comparable with
    ``bench_engine.py``'s throughput section — the comparison that matters here is
    between the columns, all of which are measured the same way.
    """
    from server.engine.metadata import MetadataProvider
    from server.engine.numeric.backend import use_backend
    from server.engine.runner import EngineRunner

    meta = MetadataProvider.from_seed_data(SEED_DIR)
    results: dict[str, Any] = {}

    for label in ["auto (default)"] + list(backend_names):
        say(f"  {label}")
        forced = None if label.startswith("auto") else label
        samples: list[float] = []
        outcome: dict[str, Any] = {}
        with use_backend(forced):
            for _ in range(repeats):
                runner = EngineRunner(meta)
                runner.init_mcat(
                    PROFILE_PROBLEM["initial"],
                    PROFILE_PROBLEM["modified"],
                    PROFILE_PROBLEM["target"],
                    seed=PROFILE_PROBLEM["seed"],
                )
                started = time.perf_counter()
                runner.run_mcat(max_steps=MAX_STEPS)
                elapsed = (time.perf_counter() - started) * 1000.0
                samples.append(elapsed)
                workspace = runner.ctx.workspace
                outcome = {
                    "status": runner.status,
                    "answer": (
                        workspace.answer_string.text if workspace.answer_string else ""
                    ),
                    "codelets": runner.ctx.codelet_count,
                    "rng_calls": runner.ctx.rng.call_count,
                }
        wall = summarise(samples)
        results[label] = {
            "wall_ms": wall,
            "rate": outcome["codelets"] / wall["min"] * 1000.0 if wall["min"] else 0.0,
            **outcome,
        }
    return results


# ──────────────────────────────────────────────────────────────────────────────
# Reporting
# ──────────────────────────────────────────────────────────────────────────────


def summarise(samples: list[float]) -> dict[str, float]:
    return {
        "min": min(samples),
        "median": statistics.median(samples),
        "max": max(samples),
        "n": len(samples),
    }


def _fmt_ms(value: float) -> str:
    if value < 0.001:
        return f"{value * 1000:.2f}µs"
    if value < 1:
        return f"{value:.3f}ms"
    if value < 1000:
        return f"{value:.2f}ms"
    return f"{value / 1000:.2f}s"


def report_scaling(rows: list[dict[str, Any]], out: Callable[[str], None]) -> None:
    labels: list[str] = []
    for row in rows:
        for label in row["backends"]:
            if label not in labels:
                labels.append(label)

    out("")
    out("Scaling — one update cycle (decay + spread + flush), state resident")
    out("=" * 78)
    header = f"{'nodes':>8}  {'edges':>9}  " + "  ".join(f"{l:>13}" for l in labels)
    out(header)
    out("-" * len(header))
    for row in rows:
        cells = []
        for label in labels:
            cell = row["backends"].get(label, {})
            if "device_ms" in cell:
                cells.append(f"{_fmt_ms(cell['device_ms']['min']):>13}")
            else:
                cells.append(f"{'—':>13}")
        out(f"{row['nodes']:>8,}  {row['edges']:>9,}  " + "  ".join(cells))

    out("")
    out("Round trip — load, update, jump candidates, apply, store (what the engine pays)")
    out("=" * 78)
    out(header)
    out("-" * len(header))
    for row in rows:
        cells = []
        for label in labels:
            cell = row["backends"].get(label, {})
            if "round_trip_ms" in cell:
                cells.append(f"{_fmt_ms(cell['round_trip_ms']['min']):>13}")
            else:
                cells.append(f"{'—':>13}")
        out(f"{row['nodes']:>8,}  {row['edges']:>9,}  " + "  ".join(cells))

    _report_crossover(rows, out)


def _report_crossover(rows: list[dict[str, Any]], out: Callable[[str], None]) -> None:
    """Where the GPU starts to win — on two measures, against two baselines.

    Both distinctions matter and quoting one number without them invites the wrong
    conclusion.

    *Which baseline.*  Against ``python`` the GPU wins early, but most of that
    margin is CPython's interpreter rather than the CPU's arithmetic.  Against
    ``numpy`` — vectorised float64 on the same machine — the comparison is device
    against device, and that is the crossover this work package is asked for.

    *Which measure.*  The kernel crossover says when the GPU is the better place
    to do the arithmetic.  The round-trip crossover says when it is the better
    place for *this engine*, which still keeps the authoritative state in a Python
    object graph and must synchronise every cycle for the probabilistic jump.  The
    second is always the later of the two, and the gap between them is the cost of
    the object graph rather than of the GPU.
    """
    out("")
    out("Crossover")
    out("=" * 78)
    for measure, label in (("device_ms", "kernel only"), ("round_trip_ms", "round trip")):
        for baseline in ("numpy", "python"):
            crossing: int | None = None
            previous: int | None = None
            detail: list[str] = []
            for row in rows:
                gpu = row["backends"].get("mlx", {}).get(measure)
                cpu = row["backends"].get(baseline, {}).get(measure)
                if not gpu or not cpu:
                    continue
                ratio = cpu["min"] / gpu["min"] if gpu["min"] else 0.0
                detail.append(
                    f"    {row['nodes']:>8,} nodes: mlx is {ratio:6.2f}x {baseline}"
                )
                if ratio > 1.0 and crossing is None:
                    crossing = row["nodes"]
                elif crossing is None:
                    previous = row["nodes"]
            if not detail:
                continue
            out(f"  [{label}] mlx (GPU, float32) against {baseline}:")
            out("\n".join(detail))
            if crossing is None:
                out(f"    -> no crossover at or below {rows[-1]['nodes']:,} nodes")
            elif previous is None:
                out(
                    f"    -> GPU already ahead at the smallest size measured "
                    f"({crossing:,})"
                )
            else:
                # The crossover is bracketed, not located: it lies somewhere
                # between the last size the CPU won and the first the GPU won, and
                # the measured sizes are an order of magnitude apart.  Quoting the
                # upper bracket as "the crossover" would imply a precision the
                # sampling does not have.
                out(
                    f"    -> crosses between {previous:,} and {crossing:,} nodes; "
                    f"GPU ahead from {crossing:,} on"
                )
            out("")

    # What the hand-written kernel bought, at every size, since that is a separate
    # question from whether the GPU is the right device at all.
    out("")
    out("  hand-written Metal kernel against composed MLX operations, same device:")
    for row in rows:
        kernel = row["backends"].get("mlx", {}).get("device_ms")
        composed = row["backends"].get("mlx-composed", {}).get("device_ms")
        if not kernel or not composed:
            continue
        out(
            f"    {row['nodes']:>8,} nodes: kernel is "
            f"{composed['min'] / kernel['min']:5.2f}x the composed graph"
        )


def report_engine(results: dict[str, Any], out: Callable[[str], None]) -> None:
    out("")
    out(
        f"Engine — {PROFILE_PROBLEM['initial']}->{PROFILE_PROBLEM['modified']}; "
        f"{PROFILE_PROBLEM['target']}? seed {PROFILE_PROBLEM['seed']}, 59-node Slipnet"
    )
    out("=" * 78)
    header = (
        f"{'backend':<16}  {'wall (min)':>11}  {'codelets/s':>11}  "
        f"{'codelets':>9}  {'rng':>8}  answer"
    )
    out(header)
    out("-" * len(header))
    reference = results.get("auto (default)")
    for label, record in results.items():
        note = ""
        if reference is not None and label != "auto (default)":
            if record["codelets"] != reference["codelets"]:
                note = "   <- different run"
            slowdown = record["wall_ms"]["min"] / reference["wall_ms"]["min"]
            note = f"  ({slowdown:.2f}x default){note}"
        out(
            f"{label:<16}  {record['wall_ms']['min']:>9.1f}ms  "
            f"{record['rate']:>11,.0f}  {record['codelets']:>9,}  "
            f"{record['rng_calls']:>8,}  {record['answer'] or '—'}{note}"
        )
    out("")
    out(
        "  A different codelet count is not a defect.  The float32 backend perturbs\n"
        "  activations in the seventh significant digit, which occasionally flips a\n"
        "  probabilistic-jump draw and from there the random stream diverges.  What\n"
        "  must not change is the *set* of reachable answers, which is the\n"
        "  expected-range oracle's question, not this benchmark's."
    )


def environment_info() -> dict[str, Any]:
    info: dict[str, Any] = {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "cpu_count": os.cpu_count(),
    }
    try:
        import numpy as np

        info["numpy"] = np.__version__
    except ImportError:
        info["numpy"] = None
    try:
        import mlx.core as mx

        info["mlx"] = mx.__version__
        info["mlx_device"] = str(mx.default_device())
    except ImportError:
        info["mlx"] = None
    return info


def load_average() -> list[float] | None:
    try:
        return list(os.getloadavg())
    except (OSError, AttributeError):  # pragma: no cover - platform dependent
        return None


# ──────────────────────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--sizes",
        default=",".join(str(s) for s in DEFAULT_SIZES),
        help="comma-separated node counts (default: %(default)s)",
    )
    parser.add_argument(
        "--backends",
        default=None,
        help="comma-separated backend names (default: every available one)",
    )
    parser.add_argument("--cycles", type=int, default=DEFAULT_CYCLES)
    parser.add_argument("--repeats", type=int, default=DEFAULT_REPEATS)
    parser.add_argument("--sections", default=",".join(SECTIONS))
    parser.add_argument("--json", dest="json_path", default=None)
    parser.add_argument("--baseline", default=None)
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    from server.engine.numeric.backend import available_backends

    sections = [s.strip() for s in args.sections.split(",") if s.strip()]
    unknown = [s for s in sections if s not in SECTIONS]
    if unknown:
        parser.error(f"unknown section(s): {', '.join(unknown)}")

    sizes = [int(s) for s in args.sizes.split(",") if s.strip()]
    names = (
        [b.strip() for b in args.backends.split(",") if b.strip()]
        if args.backends
        else available_backends()
    )

    lines: list[str] = []

    def out(text: str = "") -> None:
        lines.append(text)
        if not args.quiet:
            print(text)

    def say(text: str) -> None:
        if not args.quiet:
            print(text, file=sys.stderr)

    record: dict[str, Any] = {
        "generated": datetime.now(timezone.utc).isoformat(),
        "environment": environment_info(),
        "load_average_start": load_average(),
        "backends": names,
        "cycles": args.cycles,
        "repeats": args.repeats,
    }

    out("Petacat numeric substrate benchmark (Phase 0, WP4.5)")
    out(f"  backends: {', '.join(names)}")
    out(f"  {args.cycles} update cycles per repeat, {args.repeats} repeats, fastest reported")

    if "scaling" in sections:
        say("scaling section")
        record["scaling"] = measure_scaling(
            sizes, names, args.cycles, args.repeats, say
        )
        report_scaling(record["scaling"], out)

    if "engine" in sections:
        say("engine section")
        record["engine"] = measure_engine(names, max(3, args.repeats), say)
        report_engine(record["engine"], out)

    record["load_average_end"] = load_average()

    if args.baseline:
        with open(args.baseline) as handle:
            record["baseline"] = json.load(handle).get("generated")
        out("")
        out(f"(baseline record: {args.baseline})")

    if args.json_path:
        with open(args.json_path, "w") as handle:
            json.dump(record, handle, indent=2)
        say(f"wrote {args.json_path}")


if __name__ == "__main__":
    main()
