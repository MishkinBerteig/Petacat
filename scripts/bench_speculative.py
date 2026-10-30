#!/usr/bin/env python3
"""Wall time of one run: faithful loop vs stream-serial reference vs the speculative engine.

Run under the free-threaded interpreter (the GIL build cannot run codelets in parallel)::

    PYTHON_GIL=0 .venv-ft/bin/python scripts/bench_speculative.py \
        --out agents-workspace/wp3-speculative/bench/bench.json

For each problem it times ``run_mcat`` (faithful), the SSR, and the speculative engine at
each worker count, best of ``--repeats``, over a fixed codelet cap so the three do the same
amount of work; and it checks that every speculative run is bit-identical to the SSR.  The
JSON records the hardware, the interpreter, per-run telemetry (speculated / committed /
aborted by reason / re-executed / barriers / time in update cycles vs codelets) and the
Amdahl inputs.  The machine is shared during development: treat interim numbers as noisy.
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
try:  # WP6's measured placement: the speculative engine's threads run on the CPU backend
    from server.parallel import placement as _placement

    os.environ.setdefault("PETACAT_NUMERIC_BACKEND", _placement.speculative_backend())
except Exception:  # noqa: BLE001 - the plugin may be absent; fall back to the CPU
    os.environ.setdefault("PETACAT_NUMERIC_BACKEND", "numpy")

from server.engine import hardware  # noqa: E402
from server.engine.metadata import MetadataProvider  # noqa: E402
from server.parallel.speculative.compare import diff, run_record  # noqa: E402

PROBLEMS = [
    ("abc", "abd", "mrrjjj", None),
    ("abc", "abd", "xyz", None),
    ("eqe", "qeq", "abbbc", None),
    ("aabc", "aabd", "ijkk", None),
    ("abc", "aabbcc", "kkjjii", None),
]


def timed(meta, problem, seed, mode, workers, steps, repeats, **opts):
    best = None
    for _ in range(repeats):
        rec = run_record(meta, problem, seed, mode, workers=workers, max_steps=steps, **opts)
        if best is None or rec.seconds < best.seconds:
            best = rec
    return best


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", default="1,2,4,6,8,12,16")
    ap.add_argument("--steps", type=int, default=3000)
    ap.add_argument("--seeds", default="1,2,3")
    ap.add_argument("--repeats", type=int, default=3)
    ap.add_argument("--no-qos", action="store_true")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    workers = [int(w) for w in args.workers.split(",")]
    seeds = [int(s) for s in args.seeds.split(",")]
    meta = MetadataProvider.from_seed_data(os.path.join(ROOT, "seed_data"))
    gil = getattr(sys, "_is_gil_enabled", lambda: True)()
    machine = hardware.detect().as_dict()
    out = {
        "gil_enabled": gil, "python": sys.version, "machine": machine,
        "steps": args.steps, "seeds": seeds, "workers": workers, "repeats": args.repeats,
        "note": "shared machine during development: interim numbers are noisy",
        "problems": [],
    }
    if gil:
        print("WARNING: GIL enabled; this is not a parallelism measurement")
    for problem in PROBLEMS:
        label = f"{problem[0]}->{problem[1]}; {problem[2]}"
        entry = {"problem": label, "seeds": []}
        print(label)
        for seed in seeds:
            faithful = timed(meta, problem, seed, "faithful", 1, args.steps, args.repeats)
            ssr = timed(meta, problem, seed, "ssr", 1, args.steps, args.repeats)
            row = {"seed": seed, "codelets": ssr.codelet_count,
                   "faithful_s": faithful.seconds, "ssr_s": ssr.seconds, "spec": {}}
            line = f"  seed {seed}: faithful {faithful.seconds*1e3:7.0f} ms  ssr {ssr.seconds*1e3:7.0f} ms"
            for w in workers:
                rec = timed(meta, problem, seed, "spec", w, args.steps, args.repeats,
                            use_qos=not args.no_qos)
                exact = diff(ssr, rec) == []
                t = rec.telemetry
                row["spec"][str(w)] = {
                    "seconds": rec.seconds, "exact": exact, "speedup_vs_ssr": ssr.seconds / rec.seconds,
                    "telemetry": t,
                }
                line += f"  w{w}: {rec.seconds*1e3:6.0f}ms ({ssr.seconds/rec.seconds:4.2f}x{'' if exact else ' DIVERGED'})"
            print(line, flush=True)
            entry["seeds"].append(row)
        out["problems"].append(entry)
    # Amdahl summary: update-cycle share and serial chain per step, from the 1-worker run.
    summary = {}
    for w in workers:
        sp = [s["spec"][str(w)]["speedup_vs_ssr"] for p in out["problems"] for s in p["seeds"]]
        ab = []
        for p in out["problems"]:
            for s in p["seeds"]:
                t = s["spec"][str(w)]["telemetry"]
                spec_n = max(1, t["speculated"])
                ab.append((t["aborted_conflict"] + t["aborted_step"] + t["aborted_exception"]) / spec_n)
        summary[str(w)] = {"median_speedup_vs_ssr": statistics.median(sp),
                           "median_abort_rate": statistics.median(ab)}
    out["summary"] = summary
    out["all_exact"] = all(s["spec"][k]["exact"] for p in out["problems"] for s in p["seeds"]
                           for k in s["spec"])
    print(json.dumps(summary, indent=1), "all_exact:", out["all_exact"])
    if args.out:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        with open(args.out, "w") as f:
            json.dump(out, f, indent=1)


if __name__ == "__main__":
    main()
