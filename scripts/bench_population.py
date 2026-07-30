#!/usr/bin/env python3
"""Population throughput at K = 1, 8, 32, 128 (WP4.6).

The unit is *runs per second*, not codelets per second.  Corpus training, evolutionary
search and the expected-range oracle are all bounded by how many complete runs an hour
buys, and a change that makes one run 1.3x faster while halving how many fit on the
machine is a loss for all three.

Both strategies are measured against the same problem so the comparison is like for like:
process-parallel, which shares nothing, and batched lockstep, which is the arrangement a
GPU numeric substrate would want.

    .venv/bin/python scripts/bench_population.py [--k 1,8,32,128] [--json PATH]
"""

from __future__ import annotations

import argparse
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from server.engine.metadata import MetadataProvider  # noqa: E402
from server.engine.population import (  # noqa: E402
    BATCHING_MIN_NODES,
    batching_is_worthwhile,
    run_population,
    run_population_batched,
)

PROBLEM = ("abc", "abd", "mrrjjj")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--k", default="1,8,32,128")
    ap.add_argument("--max-steps", type=int, default=6000)
    ap.add_argument("--json", dest="json_path", default=None)
    args = ap.parse_args()

    counts = [int(k) for k in args.k.split(",")]
    meta = MetadataProvider.from_seed_data(os.path.join(REPO, "seed_data"))
    nodes = len(meta.slipnet_node_specs)

    print(
        f"Population throughput — {PROBLEM[0]}->{PROBLEM[1]}; {PROBLEM[2]}?, "
        f"{nodes}-node Slipnet\n"
    )
    print("      K   strategy     seconds   runs/s   distinct states")
    records = []
    for k in counts:
        for runner_fn, label in (
            (run_population, "process"),
            (run_population_batched, "batched"),
        ):
            result = (
                runner_fn(PROBLEM, k, max_steps=args.max_steps)
                if label == "process"
                else runner_fn(PROBLEM, k, max_steps=args.max_steps, meta=meta)
            )
            summary = result.summary()
            records.append(summary)
            print(
                f"   {k:>4}   {label:<10}{summary['seconds']:>9.2f}"
                f"{summary['runs_per_second']:>9.1f}{summary['distinct_states']:>16}"
            )
        print()

    print(
        f"   Batching worthwhile at {nodes} nodes: {batching_is_worthwhile(nodes)}\n"
        f"   (threshold {BATCHING_MIN_NODES:,} nodes, from WP4.5's measured crossover).\n"
        f"   Below it, process-parallel wins: nothing is shared, it scales with cores,\n"
        f"   and lockstep would hold every finished run hostage to the batch's slowest."
    )

    if args.json_path:
        os.makedirs(os.path.dirname(os.path.abspath(args.json_path)), exist_ok=True)
        with open(args.json_path, "w") as fh:
            json.dump({"nodes": nodes, "results": records}, fh, indent=2)
            fh.write("\n")
        print(f"\n   Wrote {args.json_path}")


if __name__ == "__main__":
    main()
