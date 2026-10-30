#!/usr/bin/env python3
"""Run one problem over many seeds on every core, and print the answer distribution.

    scripts/swarm.py abc abd mrrjjj -n 1000
    scripts/swarm.py wxyz vxyz abcd -n 1000 --seed-start 5000001 --json out.json
    scripts/swarm.py abc abd xyz --answer dyz -n 200            # justification mode
    scripts/swarm.py abc abd ijk --seeds 1-50,99 --param update_cycle_length=10
    scripts/swarm.py abc abd mrrjjj -n 200 --serial             # the serial loop, same output

A quick in-house oracle: the distribution of the answers Petacat gives, the way
``scripts/compare_to_metacat.py`` samples it, without the reference comparison.  Each run is
byte-for-byte the serial run with the same seed (``server/parallel/swarm.py``), so ``--serial``
prints the same distribution, only slower; ``--verify K`` re-runs K of the swarm's runs
in-process and checks they agree.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def parse_seeds(text: str) -> list[int]:
    """``1-50,99`` -> [1..50, 99]."""
    seeds: list[int] = []
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        lo, dash, hi = part.partition("-")
        seeds.extend(range(int(lo), int(hi) + 1) if dash else [int(lo)])
    return seeds


def parse_param(text: str) -> tuple[str, object]:
    """``name=value`` -> typed override, the type read off the shipped value."""
    from server.engine.metadata import MetadataProvider
    from server.parallel.swarm import SEED_DIR

    if "=" not in text:
        raise argparse.ArgumentTypeError(f"--param wants name=value, got {text!r}")
    name, _, raw = text.partition("=")
    name, raw = name.strip(), raw.strip()
    shipped = MetadataProvider.from_seed_data(SEED_DIR).params
    if name not in shipped:
        raise argparse.ArgumentTypeError(f"unknown engine parameter {name!r}")
    current = shipped[name]
    try:
        if isinstance(current, bool):
            return name, raw.lower() in ("true", "1", "yes")
        if isinstance(current, int):
            return name, int(raw)
        if isinstance(current, float):
            return name, float(raw)
        if isinstance(current, (list, dict)):
            return name, json.loads(raw)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"cannot read {raw!r} for {name}") from exc
    return name, raw


def main() -> int:
    from server.engine import hardware

    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("problem", nargs=3, metavar=("INITIAL", "MODIFIED", "TARGET"))
    ap.add_argument("--answer", help="justification mode: the answer to justify")
    ap.add_argument("-n", "--count", type=int, default=100)
    ap.add_argument("--seed-start", type=int, default=1)
    ap.add_argument("--seeds", help="explicit seeds, e.g. 1-50,99 (overrides -n / --seed-start)")
    ap.add_argument("--max-steps", type=int, default=20_000)
    ap.add_argument("--backend", help="numeric backend (default: the placement policy -- off at today's Slipnet size)")
    ap.add_argument("--param", action="append", type=parse_param, default=[], metavar="NAME=VALUE")
    ap.add_argument("-j", "--workers", type=int, default=0,
                    help="processes (default: every logical core but one)")
    ap.add_argument("--serial", action="store_true", help="run in this process, one at a time")
    ap.add_argument("--verify", type=int, default=0, metavar="K",
                    help="re-run K runs in-process and check they equal the swarm's")
    ap.add_argument("--top", type=int, default=15, help="distribution rows to print")
    ap.add_argument("--json", help="write the outcomes and distribution here")
    args = ap.parse_args()

    from server.engine.metadata import MetadataProvider
    from server.parallel import swarm as sw

    seeds = parse_seeds(args.seeds) if args.seeds else [args.seed_start + i for i in range(args.count)]
    overrides = dict(args.param)
    meta = MetadataProvider.from_seed_data(sw.SEED_DIR)
    backend = args.backend or sw.default_backend(meta)
    tasks = [
        sw.RunTask(*args.problem, args.answer, s, args.max_steps,
                   parameters=overrides or None, backend=backend)
        for s in seeds
    ]
    workers = 1 if args.serial else (args.workers or hardware.population_worker_count())
    mode = "justification" if args.answer else "discovery"
    print(f"{' '.join(args.problem)}"
          f"{' -> ' + args.answer if args.answer else ''}  [{mode}]  {len(seeds)} runs, "
          f"{'serial in-process' if args.serial else f'{workers} workers'}, backend {backend}"
          + (f", {overrides}" if overrides else ""))

    started = time.perf_counter()
    if args.serial:
        outcomes = [sw.run_inprocess(t, meta) for t in tasks]
        startup = 0.0
    else:
        with sw.Swarm(workers=workers, meta=meta, backend=backend) as pool:
            startup = pool.started_seconds or 0.0
            began = time.perf_counter()
            outcomes = pool.map(tasks)
            started = began
    elapsed = time.perf_counter() - started

    by_state: Counter[str] = Counter()
    quality: dict[str, list[float]] = {}
    codelets: dict[str, list[int]] = {}
    for o in outcomes:
        key = o.answer if o.status == "answer_found" and o.answer else "*NONE*"
        by_state[key] += 1
        codelets.setdefault(key, []).append(o.codelets)
        if o.answer_quality is not None and key != "*NONE*":
            quality.setdefault(key, []).append(o.answer_quality)

    total = len(outcomes)
    print(f"\n{'answer':<16}{'count':>8}{'%':>8}{'mean quality':>14}{'mean codelets':>15}")
    for answer, n in by_state.most_common(args.top):
        q = quality.get(answer)
        print(f"{answer:<16}{n:>8}{100 * n / total:>7.1f}%"
              f"{(sum(q) / len(q) if q else float('nan')):>14.1f}"
              f"{sum(codelets[answer]) / n:>15.0f}")
    if len(by_state) > args.top:
        print(f"... and {len(by_state) - args.top} more distinct answers")
    errors = [o for o in outcomes if o.error]
    total_codelets = sum(o.codelets for o in outcomes)
    print(f"\n{total} runs in {elapsed:.2f}s = {total / elapsed:.1f} runs/s, "
          f"{total_codelets / elapsed:,.0f} codelets/s"
          + (f"  (worker start-up {startup:.2f}s)" if startup else "")
          + (f"  ERRORS: {len(errors)}" if errors else ""))
    for o in errors[:3]:
        print(f"  seed {o.seed}: {o.error.strip().splitlines()[-1]}")

    if args.verify and not args.serial:
        bad = 0
        step = max(1, total // args.verify)
        for t, o in list(zip(tasks, outcomes))[::step][: args.verify]:
            if sw.run_inprocess(t, meta).fingerprint() != o.fingerprint():
                bad += 1
                print(f"  MISMATCH at seed {t.seed}")
        print(f"verify: {args.verify - bad}/{args.verify} swarm runs equal the in-process run")
        if bad:
            return 1

    if args.json:
        with open(args.json, "w") as fh:
            json.dump({
                "problem": args.problem, "answer": args.answer, "backend": backend,
                "parameters": overrides, "workers": workers, "seconds": elapsed,
                "distribution": dict(by_state.most_common()),
                "runs": [o.__dict__ for o in outcomes],
            }, fh, indent=1, default=str)
        print(f"wrote {args.json}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
