#!/usr/bin/env python3
"""Does an executor think what the faithful loop thinks?  Answer distributions, compared.

    scripts/compare_executors.py                          serial vs stream, every demo problem
    scripts/compare_executors.py --seeds 1000 --only xyz,mrrjjj
    scripts/compare_executors.py --executors serial,stream,speculative --workers 4

The parallel plugin offers executors that are *not* the faithful loop but claim the same
cognition.  The stream-serial reference (``"stream"``) changes two mechanisms -- each
codelet draws from a counter-based stream of its own, and the coderack chooses by an
exponential race rather than Metacat's two-stage draw -- and claims equality *in law*:
the same probability of every answer, by a different sequence of random numbers.  The
speculative executor claims more, bit-for-bit equality with the stream reference, which
``tests/parallel/test_speculative_exact.py`` checks run by run.

A claim in law can only be checked statistically, so this runs the same problems over
the same seeds under each executor on the swarm (every core but one) and compares the
stopping-state distributions (``status:answer``, the oracle's key) per problem:

* Pearson two-sample chi-square with rare states pooled to an expected count of 5
  (``scripts/compare_frequencies.two_sample_chi2``), and its p-value;
* total-variation distance;
* every state's two-proportion z, flagged past the Bonferroni-corrected threshold for
  the number of states compared across the whole run.

Seeds are shared between executors but that couples nothing: the executors consume them
through different generators, so the samples are independent.  Like
``compare_to_metacat.py`` this reports, it does not pass or fail: with many problems a
few small p-values are expected by chance, and the Bonferroni line says how many.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from compare_frequencies import proportion_z, total_variation, two_sample_chi2  # noqa: E402


def _problems(only: set[str] | None, include_justify: bool) -> list[tuple]:
    demo = json.load(open(os.path.join(ROOT, "seed_data", "demo_problems.json")))
    seen, out = set(), []
    for p in demo:
        justify = p["mode"] == "justification"
        if justify and not include_justify:
            continue
        key = (p["initial"], p["modified"], p["target"], p.get("answer") if justify else None)
        if key in seen:
            continue
        label = f"{key[0]}-{key[1]}-{key[2]}" + (f"={key[3]}" if key[3] else "")
        if only and not any(o in label for o in only):
            continue
        seen.add(key)
        out.append((label, key))
    return out


def _z_threshold(alpha: float, tests: int) -> float:
    """Two-sided normal quantile for alpha / tests (bisection on erfc; no scipy)."""
    target = alpha / max(1, tests)
    lo, hi = 0.0, 40.0
    for _ in range(200):
        mid = (lo + hi) / 2
        if math.erfc(mid / math.sqrt(2)) > target:
            lo = mid
        else:
            hi = mid
    return hi


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--executors", default="serial,stream",
                    help="comma-separated executor names; the first is the reference")
    ap.add_argument("--seeds", type=int, default=500, help="runs per problem per executor")
    ap.add_argument("--seed-start", type=int, default=1)
    ap.add_argument("--max-steps", type=int, default=20000)
    ap.add_argument("--only", help="comma-separated substrings of problem labels")
    ap.add_argument("--no-justify", action="store_true", help="discovery problems only")
    ap.add_argument("--problem", nargs=3, metavar=("INITIAL", "MODIFIED", "TARGET"),
                    help="compare on this one problem instead of the demo problems")
    ap.add_argument("--count-answer", help="also report each executor's rate of this answer")
    ap.add_argument("--backend", default=None, help="numeric backend (default: placement policy)")
    ap.add_argument("--workers", type=int, default=0,
                    help="within-run workers for the 'speculative' executor (default 2)")
    ap.add_argument("-j", "--jobs", type=int, default=0, help="swarm processes (default: all but one)")
    ap.add_argument("--alpha", type=float, default=0.01)
    ap.add_argument("--json", help="write the full comparison here")
    args = ap.parse_args()

    from server.parallel.swarm import RunTask, Swarm

    executors = [e.strip() for e in args.executors.split(",") if e.strip()]
    only = {o.strip() for o in args.only.split(",")} if args.only else None
    if args.problem:
        problems = [("-".join(args.problem), (*args.problem, None))]
    else:
        problems = _problems(only, include_justify=not args.no_justify)
    seeds = list(range(args.seed_start, args.seed_start + args.seeds))

    tasks = []
    for label, (initial, modified, target, answer) in problems:
        for executor in executors:
            options = None
            if executor == "speculative":
                options = {"workers": args.workers or 2}
            for seed in seeds:
                tasks.append(RunTask(
                    initial, modified, target, answer=answer, seed=seed,
                    max_steps=args.max_steps, backend=args.backend, executor=executor,
                    executor_options=options, tag=(label, executor),
                ))

    swarm = Swarm(workers=args.jobs or None)
    started = time.perf_counter()
    outcomes = swarm.map(tasks)
    elapsed = time.perf_counter() - started
    swarm.shutdown()

    states: dict[tuple, Counter] = {}
    errors = Counter()
    codelets = Counter()
    for o in outcomes:
        label, executor = o.tag
        if o.error:
            errors[(label, executor)] += 1
            continue
        states.setdefault((label, executor), Counter())[o.stopping_state] += 1
        codelets[(label, executor)] += o.codelets

    reference = executors[0]
    rows, z_all = [], []
    for label, _ in problems:
        a = states.get((label, reference), Counter())
        for other in executors[1:]:
            b = states.get((label, other), Counter())
            stat, df, p = two_sample_chi2(dict(a), dict(b))
            na, nb = sum(a.values()), sum(b.values())
            zs = {
                s: proportion_z(a.get(s, 0), na, b.get(s, 0), nb)
                for s in set(a) | set(b)
            }
            z_all.extend(zs.values())
            rows.append({
                "problem": label, "reference": reference, "other": other,
                "n": [na, nb], "chi2": stat, "df": df, "p": p,
                "tv": total_variation(dict(a), dict(b)) if na and nb else None,
                "z": zs,
                "mean_codelets": [codelets[(label, reference)] / max(1, na),
                                  codelets[(label, other)] / max(1, nb)],
                "reference_states": dict(a.most_common()),
                "other_states": dict(b.most_common()),
            })

    zcrit = _z_threshold(args.alpha, len(z_all))
    flagged_p = [r for r in rows if r["p"] is not None and r["p"] < args.alpha]
    print(f"{len(tasks)} runs in {elapsed:.1f}s ({len(tasks) / elapsed:.1f} runs/s) on "
          f"{swarm.workers} processes; errors: {sum(errors.values())}")
    print(f"{'problem':40s} {'pair':22s} {'n':>11s} {'chi2':>8s} {'df':>3s} {'p':>8s} "
          f"{'TV':>6s} {'max|z|':>7s} {'codelets':>17s}")
    for r in rows:
        zmax = max((abs(z) for z in r["z"].values()), default=0.0)
        p = "-" if r["p"] is None else f"{r['p']:.4f}"
        mark = " *" if zmax > zcrit else ""
        print(f"{r['problem'][:40]:40s} {r['reference'] + ' vs ' + r['other']:22s} "
              f"{r['n'][0]:>5d}/{r['n'][1]:<5d} {r['chi2']:8.2f} {r['df']:3d} {p:>8s} "
              f"{(r['tv'] or 0.0):6.3f} {zmax:7.2f}{mark:2s} "
              f"{r['mean_codelets'][0]:8.0f}/{r['mean_codelets'][1]:<8.0f}")
    if args.count_answer:
        for label, _ in problems:
            for executor in executors:
                counts = states.get((label, executor), Counter())
                n = sum(counts.values())
                hits = sum(v for k, v in counts.items() if k.split(":", 1)[-1] == args.count_answer)
                print(f"{label} {executor:12s} {args.count_answer}: {hits}/{n} = {hits / max(1, n):.1%}")
    expected = args.alpha * sum(1 for r in rows if r["p"] is not None)
    print(f"\nchi-square p < {args.alpha}: {len(flagged_p)} of {len(rows)} comparisons "
          f"(about {expected:.1f} expected by chance if the executors agree)")
    print(f"Bonferroni |z| > {zcrit:.2f} over {len(z_all)} state comparisons: "
          f"{sum(1 for z in z_all if abs(z) > zcrit)} flagged (marked *)")
    if args.json:
        with open(args.json, "w") as handle:
            json.dump({
                "executors": executors, "seeds": [seeds[0], seeds[-1]],
                "max_steps": args.max_steps, "backend": args.backend,
                "seconds": elapsed, "processes": swarm.workers, "alpha": args.alpha,
                "z_critical": zcrit, "errors": {f"{k[0]}|{k[1]}": v for k, v in errors.items()},
                "rows": rows,
            }, handle, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
