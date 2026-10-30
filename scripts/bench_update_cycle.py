#!/usr/bin/env python3
"""Update-cycle time against thread count (WP5).

Runs complete problems with the plugin's ``UpdateCycle`` standing in for the engine's
update cycle and times only the cycle.  Under the ``stream`` policy every thread count
does exactly the same work (the runs are bit-identical), so the per-cycle times are a
clean comparison; the engine's own cycle and the ``faithful`` policy are timed as
reference points.  Use the free-threaded interpreter, where threads run in parallel:

    .venv-ft/bin/python scripts/bench_update_cycle.py --out <file>.json

Writes JSON.  The machine is shared while other work runs, so repeat on a quiet one.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import statistics
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from server.engine.metadata import MetadataProvider  # noqa: E402
from server.engine.numeric.backend import use_backend  # noqa: E402
from server.engine.runner import EngineRunner  # noqa: E402
from server.engine.splittable_rng import SplittableRNG  # noqa: E402
from server.parallel.update_cycle import UpdateCycle, _label  # noqa: E402

PROBLEMS = [("abc", "abd", "mrrjjj"), ("wxyz", "vxyz", "abcd"),
            ("abc", "abd", "iijjkk"), ("eqe", "qeq", "abbba")]


def bench(meta, policy, threads, min_items, seeds, max_steps, parallel_posting=False, spin_us=3000.0):
    """Return (microseconds per cycle, cycles, phase microseconds per cycle)."""
    original = EngineRunner.update_everything
    spent = 0.0
    cycles = 0
    phases: dict[str, float] = {}
    for problem in PROBLEMS:
        for seed in seeds:
            EngineRunner.update_everything = original
            r = EngineRunner(meta)
            r.init_mcat(*problem, seed=seed)
            base = SplittableRNG(seed)
            if policy == "engine":
                def patched(self, _o=original):
                    nonlocal spent, cycles
                    t = time.perf_counter()
                    _o(self)
                    spent += time.perf_counter() - t
                    cycles += 1
                cyc = None
            else:
                cyc = UpdateCycle(r, policy, threads, force_threads=threads > 1,
                                  min_items=min_items, profile=True,
                                  parallel_posting=parallel_posting, spin_us=spin_us)

                def patched(self, _c=cyc, _b=base):
                    nonlocal spent, cycles
                    t = time.perf_counter()
                    if policy == "stream":
                        _c.run(_b.split(_label("update", self._update_cycle + 1)))
                    else:
                        _c.run()
                    spent += time.perf_counter() - t
                    cycles += 1
            EngineRunner.update_everything = patched
            try:
                r.run_mcat(max_steps=max_steps)
            finally:
                EngineRunner.update_everything = original
                if cyc is not None:
                    for k, v in cyc.phase_times.items():
                        phases[k] = phases.get(k, 0.0) + v
                    cyc.close()
    return (1e6 * spent / max(cycles, 1), cycles,
            {k: 1e6 * v / max(cycles, 1) for k, v in phases.items()})


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--threads", type=int, nargs="+", default=[1, 2, 3, 4, 6, 8, 12])
    ap.add_argument("--seeds", type=int, default=4)
    ap.add_argument("--max-steps", type=int, default=3000)
    ap.add_argument("--repeats", type=int, default=3)
    ap.add_argument("--min-items", type=int, nargs="+", default=[1, 8, 16])
    ap.add_argument("--spin-us", type=float, default=3000.0)
    ap.add_argument("--backends", nargs="+", default=["off", "numpy"])
    a = ap.parse_args()
    meta = MetadataProvider.from_seed_data("seed_data")
    seeds = list(range(1, a.seeds + 1))
    out = {
        "python": sys.version, "gil": getattr(sys, "_is_gil_enabled", lambda: True)(),
        "machine": platform.machine(), "cpus": os.cpu_count(),
        "loadavg": os.getloadavg(), "note": "machine shared with other work; noisy",
        "seeds": seeds, "max_steps": a.max_steps, "problems": PROBLEMS, "results": [],
    }
    for backend in a.backends:
        with use_backend(backend):
            configs = [("engine", 1, 0), ("faithful", 1, 0)]
            for mi in a.min_items:
                configs += [("stream", t, mi) for t in a.threads]
            configs += [("faithful", t, 1) for t in a.threads if t in (2, 4, 8)]
            for policy, threads, mi in configs:
                runs = [bench(meta, policy, threads, mi, seeds, a.max_steps, spin_us=a.spin_us)
                        for _ in range(a.repeats)]
                best = min(runs, key=lambda x: x[0])
                row = {"backend": backend, "policy": policy, "threads": threads,
                       "min_items": mi, "us_per_cycle_best": best[0],
                       "us_per_cycle_median": statistics.median(r[0] for r in runs),
                       "cycles": best[1], "phase_us_per_cycle": best[2]}
                out["results"].append(row)
                print(f"{backend:6s} {policy:9s} threads={threads:2d} min_items={mi:2d} "
                      f"best={row['us_per_cycle_best']:7.1f} us/cycle  "
                      f"median={row['us_per_cycle_median']:7.1f}", flush=True)
            json.dump(out, open(a.out, "w"), indent=1)
    json.dump(out, open(a.out, "w"), indent=1)


if __name__ == "__main__":
    main()
