#!/usr/bin/env python3
"""Swarm scaling: runs per second against worker count, per numeric backend.

    .venv/bin/python scripts/bench_swarm.py                       # off + numpy, full ladder
    .venv/bin/python scripts/bench_swarm.py --backends numpy,mlx --mlx-seeds 2
    .venv/bin/python scripts/bench_swarm.py -o measurements/parallel/swarm-scaling.json

A fixed mix of demo problems (discovery and justification) x seeds is run through a
warm :class:`server.parallel.swarm.Swarm` at 1, 2, 4, 8, ... up to every core but one,
once per backend.  Every worker count executes the *same* tasks, so the script also
checks the outcomes are identical across worker counts: a scaling number from a swarm
that changed what a run does would be worth nothing.

What it reports, per backend
    runs/s and codelets/s at each worker count, speed-up over one worker, and scaling
    efficiency (speed-up / workers) -- both against one *swarm* worker and against the
    plain in-process serial loop;
    the per-process codelet rate at full load, sorted, which on a machine with two core
    tiers (Apple's "Super" and "Performance", or P and E) shows the tiers as steps.

The JSON carries ``hardware.detect().as_dict()`` so a figure says which machine made it.
A machine shared with other work gives noisy figures; ``load_average`` is recorded at the
start of each measurement for that reason.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

#: Problems of different cost and kind: quick discovery, slow discovery, justification.
MIX = (
    ("abc", "abd", "ijk", None),
    ("abc", "abd", "mrrjjj", None),
    ("abc", "abd", "xyz", None),
    ("aabc", "aabd", "ijkk", None),
    ("xqc", "xqd", "mrrjjj", "mrrjjjj"),
    ("wxyz", "vxyz", "abcd", None),
)


def build_tasks(seeds: int, max_steps: int, backend: str):
    from server.parallel.swarm import RunTask

    return [
        RunTask(i, m, t, a, seed, max_steps, backend=backend)
        for seed in range(1, seeds + 1)
        for (i, m, t, a) in MIX
    ]


def measure(workers: int, tasks, meta) -> dict:
    from server.parallel.swarm import Swarm

    load = os.getloadavg()[0]
    with Swarm(workers=workers, meta=meta) as sw:
        startup = sw.started_seconds
        began = time.perf_counter()
        outcomes = sw.map(tasks)
        seconds = time.perf_counter() - began
    errors = [o.error for o in outcomes if o.error]
    codelets = sum(o.codelets for o in outcomes)
    by_pid: dict[int, list] = defaultdict(lambda: [0, 0.0, 0])
    for o in outcomes:
        entry = by_pid[o.worker_pid]
        entry[0] += o.codelets
        entry[1] += o.seconds
        entry[2] += 1
    rates = sorted((c / s for c, s, _ in by_pid.values() if s > 0), reverse=True)
    return {
        "workers": workers,
        "runs": len(outcomes),
        "seconds": round(seconds, 3),
        "runs_per_second": round(len(outcomes) / seconds, 2),
        "codelets": codelets,
        "codelets_per_second": round(codelets / seconds),
        "startup_seconds": round(startup, 3),
        "errors": errors[:3],
        "load_average_1m": round(load, 2),
        "per_process_codelets_per_second": [round(r) for r in rates],
        "_fingerprints": [o.fingerprint() for o in outcomes],
    }


def serial_baseline(tasks, meta) -> dict:
    from server.parallel.swarm import run_inprocess

    began = time.perf_counter()
    outcomes = [run_inprocess(t, meta) for t in tasks]
    seconds = time.perf_counter() - began
    codelets = sum(o.codelets for o in outcomes)
    return {
        "runs": len(outcomes), "seconds": round(seconds, 3),
        "runs_per_second": round(len(outcomes) / seconds, 2),
        "codelets_per_second": round(codelets / seconds),
        "_fingerprints": [o.fingerprint() for o in outcomes],
    }


def main() -> int:
    from server.engine import hardware
    from server.engine.metadata import MetadataProvider
    from server.parallel import qos
    from server.parallel.swarm import SEED_DIR

    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--backends", default="off,numpy")
    ap.add_argument("--workers", help="comma list; default is the ladder 1,2,4,.. up to all-but-one")
    ap.add_argument("--seeds", type=int, default=16, help="seeds per problem in the mix")
    ap.add_argument("--mlx-seeds", type=int, default=2, help="seeds per problem for mlx (it is slow)")
    ap.add_argument("--max-steps", type=int, default=6000)
    ap.add_argument("--no-serial", action="store_true", help="skip the in-process serial baseline")
    ap.add_argument("-o", "--out", default="agents-workspace/wp2-swarm/bench_swarm.json")
    args = ap.parse_args()

    meta = MetadataProvider.from_seed_data(SEED_DIR)
    top = hardware.population_worker_count()
    ladder = (
        [int(x) for x in args.workers.split(",")] if args.workers else hardware.worker_ladder(top)
    )
    record = {
        "benchmark": "swarm scaling",
        "date": time.strftime("%Y-%m-%d %H:%M:%S"),
        "machine": hardware.detect().as_dict(),
        "core_tiers": qos.describe_core_tiers().as_dict(),
        "python": sys.version.split()[0],
        "problem_mix": [list(p) for p in MIX],
        "max_steps": args.max_steps,
        "ladder": ladder,
        "backends": {},
        "note": "Measured on a machine that may be shared; see load_average_1m per row.",
    }

    for backend in args.backends.split(","):
        seeds = args.mlx_seeds if backend.startswith("mlx") else args.seeds
        tasks = build_tasks(seeds, args.max_steps, backend)
        print(f"\n== backend {backend}: {len(tasks)} runs ({len(MIX)} problems x {seeds} seeds)")
        entry: dict = {"runs": len(tasks), "rows": []}
        reference = None
        if not args.no_serial:
            base = serial_baseline(tasks, meta)
            reference = base.pop("_fingerprints")
            entry["serial_inprocess"] = base
            print(f"   serial in-process : {base['seconds']:8.2f}s  {base['runs_per_second']:7.2f} runs/s")
        rows = []
        for n in ladder:
            row = measure(n, tasks, meta)
            prints = row.pop("_fingerprints")
            if reference is None:
                reference = prints
            row["identical_to_serial"] = prints == reference
            rows.append(row)
            one = rows[0]["runs_per_second"]
            row["speedup_vs_1_worker"] = round(row["runs_per_second"] / one, 2)
            row["efficiency_vs_1_worker"] = round(row["runs_per_second"] / one / n, 3)
            if "serial_inprocess" in entry:
                row["speedup_vs_serial"] = round(
                    row["runs_per_second"] / entry["serial_inprocess"]["runs_per_second"], 2
                )
            print(
                f"   {n:3d} workers : {row['seconds']:8.2f}s  {row['runs_per_second']:7.2f} runs/s"
                f"  x{row['speedup_vs_1_worker']:<6} eff {row['efficiency_vs_1_worker']:.2f}"
                f"  identical={row['identical_to_serial']}  load={row['load_average_1m']}"
            )
        entry["rows"] = rows
        if rows and rows[-1]["per_process_codelets_per_second"]:
            r = rows[-1]["per_process_codelets_per_second"]
            print(f"   per-process codelets/s at {rows[-1]['workers']} workers: "
                  f"max {r[0]}, median {int(statistics.median(r))}, min {r[-1]}")
        record["backends"][backend] = entry

    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w") as fh:
        json.dump(record, fh, indent=2)
    print(f"\nwrote {args.out}")
    return 0 if all(
        r["identical_to_serial"] and not r["errors"]
        for e in record["backends"].values() for r in e["rows"]
    ) else 1


if __name__ == "__main__":
    sys.exit(main())
