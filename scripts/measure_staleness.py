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
    Baseline,
    check_problem,
    default_workers,
    p50_states,
    problem_label,
    sample_problem,
    worker_pool,
)

DEFAULT_DELAYS = (0, 1, 5, 15, 50)
DEFAULT_RUNS = 150

#: Problems to sweep.  Previously taken from the committed expected-range fixture;
#: that fixture is gone, so the catalogue comes from the seed data instead and the
#: baseline is measured here — see :func:`baseline_at_zero`.
CATALOGUE = os.path.join(REPO, "seed_data", "demo_problems.json")


def catalogue_problems(only: str | None = None) -> list[dict]:
    """The distinct analogy problems, deduplicated by (initial, modified, target).

    ``demo_problems.json`` lists 40 entries but many are the same problem under a
    different section heading, and a staleness sweep wants each distinct problem
    once.  The first entry for a triple supplies its name.
    """
    with open(CATALOGUE) as fh:
        entries = json.load(fh)
    seen: dict[tuple[str, str, str], dict] = {}
    for e in entries:
        key = (e["initial"], e["modified"], e["target"])
        if key not in seen:
            seen[key] = {"name": e["name"], "initial": e["initial"],
                         "modified": e["modified"], "target": e["target"]}
    problems = list(seen.values())
    if only:
        problems = [p for p in problems if p["name"] == only]
        if not problems:
            sys.exit(f"no problem named {only!r} in {CATALOGUE}")
    return problems


def baseline_at_zero(problems: list[dict], runs: int, workers: int) -> Baseline:
    """Measure the baseline here, at delay 0, rather than reading a committed one.

    This used to load ``tests/fixtures/expected_range.json``, a saturated sample of
    Petacat's own behaviour.  That fixture has been retired: Petacat is now measured
    against Metacat's published sets, and a self-sampled baseline could only ever
    detect drift from its own past.

    Metacat's sets are the wrong reference for *this* script, though, and swapping
    one for the other would have been the obvious mistake.  The question here is not
    "does Petacat agree with Metacat" but "at what delay does staleness change what
    this engine reaches" — a within-engine comparison by construction.  Against
    Metacat every pre-existing divergence would appear at every delay including
    zero, burying the signal in a constant offset.

    So delay 0 is the baseline, which is what the script already sampled as a
    control.  The states it reaches, and their p50 subset, are what each delay above
    zero is compared against.  One consequence worth holding on to: a sample this
    size is not saturated the way the retired fixture was, so a novel state at a
    higher delay is weaker evidence than it used to be, while a *missing* p50 state
    means the same thing it always did.
    """
    run_one = functools.partial(run_with_staleness, delay=0)
    records: list[dict] = []
    with worker_pool(workers=workers, run_one=run_one) as pool:
        for problem in problems:
            observed = sample_problem(problem, runs, pool=pool, max_steps=MAX_STEPS)
            record = dict(problem)
            record["counts"] = dict(observed)
            record["expected_range"] = sorted(observed)
            record["distinct_states"] = len(observed)
            singletons = sum(1 for c in observed.values() if c == 1)
            total = sum(observed.values())
            record["f1_over_n"] = (singletons / total) if total else 0.0
            record["absence_check"] = {"states": p50_states(record)}
            records.append(record)
            print(
                f"    {record['name']:<14} {problem_label(record):<24} "
                f"states={len(observed):>3}  p50={len(record['absence_check']['states'])}"
                f"  f1/n={record['f1_over_n']:.4f}",
                flush=True,
            )
    return Baseline(
        path=f"measured at delay 0, {runs} runs/problem",
        criterion={"source": "delay-0 control sample", "runs": runs,
                   "max_steps": MAX_STEPS},
        totals={"problems": len(records), "runs": runs * len(records)},
        problems=tuple(records),
    )


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
    problems = catalogue_problems(args.problem)

    # Delay 0 is measured first and becomes the reference for every delay above it.
    # It is still swept as a control below, where it must come back empty: a
    # non-empty result at delay 0 means the sample is not reproducible run to run,
    # which invalidates the whole sweep rather than saying anything about staleness.
    print(f"Baseline: {len(problems)} problems x {args.runs} runs at delay 0",
          flush=True)
    baseline = baseline_at_zero(problems, args.runs, args.workers)

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
