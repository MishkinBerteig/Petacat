#!/usr/bin/env python3
"""Measure how much stale state Petacat's cognition absorbs (WP0.5).

Free-running execution (WP4.4) lets codelets run with no global barrier, so a
codelet decides on a Workspace that has moved on by the time it commits.  Whether
that breaks the model is the central risk of the whole parallelism workstream, and
it is far cheaper to answer before the concurrency is written than after.

So this answers it serially.  ``EngineContext.set_staleness_delay(N)`` makes each
codelet read the Workspace as it stood N codelets ago while the loop stays strictly
one-codelet-at-a-time — no threads, no locks, no scheduler changes.  The
expected-range oracle (WP0.1) then says at what N the set of reachable stopping
states starts to move, and that N is an upper bound on the staleness free-running
can afford.

Reading the result
------------------
Two signals, and they mean different things:

* A **missing** absence-check state is decisive.  Those are the most-frequent states
  of a problem, summing to at least half its baseline sample; at these sample sizes
  their absence is not a sampling accident.  When one goes missing the delay has
  changed what the program can perceive.

* **Novel** states are weaker evidence and are expected at a low rate even with a
  correct engine — the baseline is saturated, not exhaustive, and ``f1_over_n``
  predicts roughly a 1% chance per problem per 100-run sample.  A novel state at
  N=0 is that false-alarm rate; a jump in novel states as N grows is the delay
  opening paths the live engine does not take.

N=0 is sampled as a control.  It exercises the same code path with the mechanism
switched off, so a non-empty result there means the harness is at fault, not the
staleness.

Usage
-----
    python3 scripts/measure_staleness.py [--runs N] [--delays 0,1,5,15,50]
                                         [--workers N] [--json PATH] [--problem NAME]
"""

from __future__ import annotations

import argparse
import functools
import json
import os
import sys
import time
from collections import Counter

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from server.engine.metadata import MetadataProvider  # noqa: E402
from server.engine.runner import EngineRunner  # noqa: E402
from tests.support.expected_range import (  # noqa: E402
    MAX_STEPS,
    check_problem,
    default_workers,
    load_baseline,
    problem_label,
    sample_problem,
    worker_pool,
)

DEFAULT_DELAYS = (0, 1, 5, 15, 50)
DEFAULT_RUNS = 150


def run_with_staleness(
    meta: MetadataProvider, problem: dict, seed: int, max_steps: int, *, delay: int
) -> str:
    """One discovery run at a fixed staleness delay.

    Matches ``tests.support.expected_range.default_run_one`` in every other respect,
    including the stopping-state key, so the samples are comparable with the
    baseline.  ``functools.partial`` binds the delay; the result stays picklable
    because this is a module-level function, which the worker pool requires.
    """
    runner = EngineRunner(meta)
    runner.init_mcat(
        problem["initial"], problem["modified"], problem["target"], seed=seed
    )
    if delay:
        runner.ctx.set_staleness_delay(delay)
    runner.run_mcat(max_steps=max_steps)
    workspace = runner.ctx.workspace
    answer = workspace.answer_string.text if workspace.answer_string else ""
    return f"{runner.status}:{answer}"


def measure_delay(
    baseline, delay: int, runs: int, workers: int, verbose: bool = True
) -> dict:
    """Sample every problem at one delay and compare against the baseline."""
    run_one = functools.partial(run_with_staleness, delay=delay)
    started = time.perf_counter()
    problems: list[dict] = []

    with worker_pool(workers=workers, run_one=run_one) as pool:
        for record in baseline:
            observed: Counter = sample_problem(
                record, runs, pool=pool, max_steps=MAX_STEPS
            )
            result = check_problem(record, observed)
            problems.append(
                {
                    "name": record["name"],
                    "label": problem_label(record),
                    "distinct_states_observed": len(observed),
                    "distinct_states_in_baseline": record["distinct_states"],
                    "novel": sorted(result.novel),
                    "missing": sorted(result.missing),
                    "ok": result.ok,
                }
            )
            if verbose:
                flag = "" if result.ok and not result.novel else "   <-- moved"
                print(
                    f"    {record['name']:<14} {problem_label(record):<24} "
                    f"states={len(observed):>3}  novel={len(result.novel):>2}  "
                    f"missing={len(result.missing):>2}{flag}",
                    flush=True,
                )

    return {
        "delay": delay,
        "runs_per_problem": runs,
        "seconds": round(time.perf_counter() - started, 1),
        "total_novel": sum(len(p["novel"]) for p in problems),
        "total_missing": sum(len(p["missing"]) for p in problems),
        "problems_with_missing": [p["name"] for p in problems if p["missing"]],
        "problems_with_novel": [p["name"] for p in problems if p["novel"]],
        "problems": problems,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--runs", type=int, default=DEFAULT_RUNS,
                    help=f"runs per problem per delay (default {DEFAULT_RUNS})")
    ap.add_argument("--delays", default=",".join(str(d) for d in DEFAULT_DELAYS),
                    help="comma-separated codelet delays to sweep")
    ap.add_argument("--workers", type=int, default=default_workers())
    ap.add_argument("--problem", default=None, help="restrict to one problem by name")
    ap.add_argument("--json", dest="json_path", default=None)
    args = ap.parse_args()

    delays = [int(d) for d in args.delays.split(",") if d.strip()]
    baseline = load_baseline()
    if args.problem:
        baseline = type(baseline)(
            path=baseline.path,
            criterion=baseline.criterion,
            totals=baseline.totals,
            problems=tuple(r for r in baseline if r["name"] == args.problem),
        )
        if not len(baseline):
            sys.exit(f"no problem named {args.problem!r} in the baseline")

    print(
        f"Staleness sweep: {len(baseline)} problems x {args.runs} runs x "
        f"{len(delays)} delays = {len(baseline) * args.runs * len(delays):,} runs, "
        f"{args.workers} workers",
        flush=True,
    )

    results = []
    overall = time.perf_counter()
    for delay in delays:
        label = "live (control)" if delay == 0 else f"{delay} codelets behind"
        print(f"\n  delay={delay}  [{label}]", flush=True)
        result = measure_delay(baseline, delay, args.runs, args.workers)
        results.append(result)
        print(
            f"    -> novel={result['total_novel']}  "
            f"missing={result['total_missing']}  ({result['seconds']}s)",
            flush=True,
        )

    print("\n  delay   novel   missing   problems that lost a frequent state")
    for r in results:
        lost = ", ".join(r["problems_with_missing"]) or "-"
        print(f"  {r['delay']:>5}   {r['total_novel']:>5}   {r['total_missing']:>7}   {lost}")

    moved = [r["delay"] for r in results if r["total_missing"]]
    if moved:
        print(
            f"\n  The expected range first loses a frequent state at delay "
            f"{min(moved)}. Free-running must keep staleness below that."
        )
    else:
        print(
            f"\n  No frequent state was lost at any delay up to {max(delays)}. "
            f"Either cognition absorbs this much staleness, or {args.runs} runs per "
            f"problem is too few to show it — re-run with --runs raised before "
            f"concluding the former."
        )

    if args.json_path:
        payload = {
            "generated_by": "scripts/measure_staleness.py",
            "runs_per_problem": args.runs,
            "workers": args.workers,
            "max_steps_per_run": MAX_STEPS,
            "baseline": baseline.path,
            "seconds": round(time.perf_counter() - overall, 1),
            "delays": results,
        }
        os.makedirs(os.path.dirname(os.path.abspath(args.json_path)), exist_ok=True)
        with open(args.json_path, "w") as fh:
            json.dump(payload, fh, indent=2)
            fh.write("\n")
        print(f"\n  Wrote {args.json_path}")


if __name__ == "__main__":
    main()
