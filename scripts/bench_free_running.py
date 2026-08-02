#!/usr/bin/env python3
"""Measure free-running execution across worker counts (WP4.4).

Reports what the plan asks for: throughput and conflict-rate telemetry across a ladder
of worker counts, against the serial loop.  The ladder is powers of two up to the
machine's own worker count — its performance cores — so the measurement covers the
range this machine can actually run and stops there.  ``--workers`` names a ladder
explicitly.

**Run this under the free-threaded interpreter.** Under the standard build the GIL
serialises the codelet bodies, so every worker count measures the same thing plus
scheduling overhead — the numbers are not wrong, they are simply not about parallelism:

    PYTHON_GIL=0 .venv-ft/bin/python scripts/bench_free_running.py

The ceiling to judge against is WP1.2's recomputed Amdahl figure: codelet execution is
**40.1% of runtime**, so parallelising it alone caps speedup at **1.67x**, and the
free-threaded interpreter costs about 9% single-threaded on top of that. Anything near
1.5x is close to the arithmetic limit of what parallelising codelets *can* give, and the
remaining serial fraction is the coderack maintenance and the numeric substrate.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from server.engine import hardware  # noqa: E402
from server.engine.free_running import FreeRunningEngine  # noqa: E402
from server.engine.metadata import MetadataProvider  # noqa: E402
from server.engine.runner import EngineRunner  # noqa: E402

SEED_DIR = os.path.join(REPO, "seed_data")
PROBLEMS = [
    ("abc", "abd", "mrrjjj", 42),
    ("abc", "abd", "iijjkk", 42),
    ("abc", "abd", "xyz", 7),
]


def serial_baseline(meta, problem, max_steps: int, repeats: int) -> dict:
    initial, modified, target, seed = problem
    best = None
    codelets = 0
    for _ in range(repeats):
        runner = EngineRunner(meta)
        runner.init_mcat(initial, modified, target, seed=seed)
        started = time.perf_counter()
        result = runner.run_mcat(max_steps=max_steps)
        elapsed = time.perf_counter() - started
        if best is None or elapsed < best:
            best, codelets = elapsed, result.codelet_count
    return {
        "workers": 0,
        "seconds": round(best, 4),
        "codelets": codelets,
        "codelets_per_second": round(codelets / best) if best else 0,
        "conflict_rate": 0.0,
    }


def free_running(meta, problem, workers: int, max_steps: int, repeats: int) -> dict:
    initial, modified, target, seed = problem
    best = None
    for _ in range(repeats):
        runner = EngineRunner(meta)
        runner.init_mcat(initial, modified, target, seed=seed)
        engine = FreeRunningEngine(runner, workers=workers)
        result = engine.run(max_steps=max_steps)
        if best is None or result.seconds < best.seconds:
            best = result
    return best.summary()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--workers",
        default=None,
        help="Comma-separated worker counts. Default: powers of two up to this "
             "machine's performance core count.",
    )
    ap.add_argument("--max-steps", type=int, default=2000)
    ap.add_argument("--repeats", type=int, default=3)
    ap.add_argument("--json", dest="json_path", default=None)
    args = ap.parse_args()

    gil = getattr(sys, "_is_gil_enabled", lambda: True)()
    machine = hardware.detect()
    worker_counts = (
        [int(w) for w in args.workers.split(",")]
        if args.workers
        else hardware.worker_ladder()
    )
    meta = MetadataProvider.from_seed_data(SEED_DIR)

    print(
        f"Free-running — {args.max_steps} codelet cap, best of {args.repeats}, "
        f"GIL {'ENABLED (not a parallelism measurement)' if gil else 'disabled'}\n"
        f"  {machine.cpu.chip or machine.platform}: "
        f"{machine.cpu.performance_cores} performance + "
        f"{machine.cpu.efficiency_cores} efficiency cores, "
        f"workers {worker_counts}\n"
    )
    if gil:
        print(
            "   WARNING: the GIL is on, so codelet bodies do not execute in parallel.\n"
            "   Re-run as: PYTHON_GIL=0 .venv-ft/bin/python scripts/bench_free_running.py\n"
        )

    records: dict = {
        "gil_enabled": gil,
        "max_steps": args.max_steps,
        "machine": machine.as_dict(),
        "worker_counts": worker_counts,
        "problems": {},
    }

    for problem in PROBLEMS:
        label = f"{problem[0]}->{problem[1]}; {problem[2]}? (seed {problem[3]})"
        print(f"  {label}")
        print(
            "     mode        workers   codelets    wall ms   codelets/s   speedup  "
            "conflicts"
        )

        base = serial_baseline(meta, problem, args.max_steps, args.repeats)
        print(
            f"     serial      {'-':>7}{base['codelets']:>11}"
            f"{base['seconds'] * 1000:>11.0f}{base['codelets_per_second']:>13,}"
            f"{'1.00x':>10}{'-':>11}"
        )

        rows = [base]
        for workers in worker_counts:
            row = free_running(meta, problem, workers, args.max_steps, args.repeats)
            speedup = (
                row["codelets_per_second"] / base["codelets_per_second"]
                if base["codelets_per_second"]
                else 0.0
            )
            row["speedup"] = round(speedup, 3)
            rows.append(row)
            print(
                f"     free      {workers:>9}{row['codelets']:>11}"
                f"{row['seconds'] * 1000:>11.0f}{row['codelets_per_second']:>13,}"
                f"{speedup:>9.2f}x{row['conflict_rate']:>11.3f}"
            )
        records["problems"][label] = rows
        print()

    print(
        "   Ceiling: WP1.2 measured codelet execution at 40.1% of runtime, so\n"
        "   parallelising it alone caps speedup at 1.67x, and free-threading costs\n"
        "   about 9% single-threaded on top. The remaining serial fraction is coderack\n"
        "   maintenance and the numeric substrate."
    )

    if args.json_path:
        os.makedirs(os.path.dirname(os.path.abspath(args.json_path)), exist_ok=True)
        with open(args.json_path, "w") as fh:
            json.dump(records, fh, indent=2)
            fh.write("\n")
        print(f"\n   Wrote {args.json_path}")


if __name__ == "__main__":
    main()
