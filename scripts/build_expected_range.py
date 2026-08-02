#!/usr/bin/env python3
"""Build the expected-range baseline — the regression oracle for Petacat.

Petacat is stochastic by design: the same problem reaches different valid stopping
states on different runs, and that variation is correct behaviour rather than a
defect.  So the oracle is not a single seeded run, and it is not a frequency
distribution.  It is the **set of stopping states a problem can reach**.

Set membership is the right invariant because it is what survives the changes the
engine is going to undergo.  Reordering codelets — a different scheduler, a different
random stream, concurrent execution — changes *which* state a given seed produces and
*how often* each occurs.  It should not change *which states are reachable*.  A
frequency-based oracle breaks on every such change and cannot separate expected drift
from regression; a set-based one should not move at all.

Saturation criterion
--------------------
Sampling stops on the Good-Turing missing-mass estimate ``f1 / N``, where ``f1`` is the
number of states seen exactly once.  It estimates the probability that the next run
produces a state never seen before, so it measures the thing we actually care about:
how complete the set is.

A fixed "N runs with no new state" rule is not good enough, and measurably so.  On
``abc -> abd; xyz -> ?`` the true set has 35 states, with six inter-discovery gaps
longer than 1000 runs (1124, 2595, 1275, 1851, 2676, 3068).  A 1000-run gap rule stops
at run 3933 holding 22 of 35 states — missing 37% of the set, and missing it silently.
Every absent state would later present as a false regression.  At that same point
``f1/N`` was still ~0.002, twenty-five times its saturated value, correctly reporting
"keep going".

The target band is ``TARGET_LOWER < f1/N <= TARGET_UPPER``.  The upper bound says
saturated; the lower bound says stop rather than burn runs driving an already-adequate
estimate lower.  Overshooting below the band is harmless to correctness — the baseline
is simply larger than it needed to be — and is reported so batch size can be tuned.

``f1/N`` also predicts the false-alarm rate of the cheap check that uses this baseline:
at ``f1/N = 0.0001`` a 100-run check has roughly a 1% chance per problem of surfacing a
state that was always reachable but had not yet been seen.

Absence checking — the p50 set
------------------------------
The set test is one-sided: it catches states appearing, not states lost.  So the
baseline also records the **p50 set**: the smallest group of most-frequent states whose
combined frequency reaches 50%, under ``absence_check``.  Those are common enough that
their absence from a 100-run check is real evidence — a state at 57% is absent from 100
runs with probability ~1e-36 — while rarer states are ignored in both directions,
because their absence means nothing at that sample size.  A checker missing one of them
is looking at a regression; ``counts`` records the full distribution, so the same set is
derivable from the record directly.

Scope
-----
Every unique ``(initial, modified, target)`` triple across all demo problems, run in
discovery mode.  Demos catalogued as justification contribute their triple with the
supplied answer dropped — justification *mode* is not carried forward past Phase 0, but
the analogy problems themselves are perfectly good and excluding them would shrink the
baseline for no reason.  Duplicate triples are merged: 34 demos reduce to 13 problems.

The numeric backend
-------------------
A sample belongs to the backend that produced it, so the backend is pinned in every
worker and recorded in ``criterion.numeric_backend``.  The default is vectorised
float64 on the CPU, which is the reference's own arithmetic; ``--backend`` runs the
sample somewhere else, and writing such a sample requires an explicit ``--out``, so
the committed baseline stays the float64 sample it says it is.  What a sample from
another backend is *for* is adjudication: when a check surfaces a state the baseline
does not list, a deep re-sample on the backend that produced it is the evidence the
decision needs.

Usage
-----
    python3 scripts/build_expected_range.py [--out PATH] [--workers N] [--problem NAME]
                                            [--backend NAME]
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
import time
from collections import Counter
from multiprocessing import Pool

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from server.engine.metadata import MetadataProvider  # noqa: E402
from server.engine.runner import EngineRunner  # noqa: E402

SEED_DIR = os.path.join(REPO, "seed_data")
DEFAULT_OUT = os.path.join(REPO, "tests", "fixtures", "expected_range.json")

# Saturation band on the Good-Turing missing-mass estimate f1/N.
TARGET_UPPER = 0.0001
TARGET_LOWER = 0.00006

BATCH = 1000       # runs between saturation checks
MIN_RUNS = 3000    # floor before any stop is allowed
# When f1 == 0 the Good-Turing estimate is 0, which cannot distinguish "complete"
# from "under-sampled" -- the classic small-sample failure of the statistic. Require
# at least 1/TARGET_UPPER runs before accepting it, on the reasoning that f1 == 0
# below that threshold is *weaker* evidence than f1 == 1 at that threshold, which the
# band itself would reject. Measured need: abc->cba; mrrjjj? and eqe->qeq; abbba?
# both reported f1 == 0 at N=3000 while their rarest observed state had been seen
# only 2-3 times.
MIN_RUNS_IF_NO_SINGLETONS = int(1 / TARGET_UPPER)
MAX_RUNS = 200000  # backstop against a problem that never saturates
MAX_STEPS = 6000   # per-run codelet cap

# Candidate backends for a worker, most preferred first: the first one whose
# dependency is importable is taken. Vectorised float64 where NumPy is installed, the
# reference loops where it is not — both compute in the reference's precision, so the
# committed baseline is a float64 sample either way.
DEFAULT_BACKENDS = ("numpy", "python")

# The module each backend name needs. ``python`` is the reference and needs nothing.
BACKEND_REQUIREMENT = {
    "python": None,
    "numpy": "numpy",
    "mlx": "mlx.core",
    "mlx-cpu": "mlx.core",
}

_META: MetadataProvider | None = None


def resolve_backend(candidates: tuple[str, ...]) -> str:
    """The first candidate whose dependency is importable.

    ``importlib.util.find_spec`` locates a module without executing it, which keeps
    the answer free of whatever an import would initialise.
    """
    for name in candidates:
        requirement = BACKEND_REQUIREMENT.get(name, name)
        if requirement is None or importlib.util.find_spec(requirement) is not None:
            return name
    return "python"


def _init_worker(backend: str) -> None:
    """Pin the backend before the first engine object exists, then load the metadata."""
    global _META
    os.environ["PETACAT_NUMERIC_BACKEND"] = backend
    _META = MetadataProvider.from_seed_data(SEED_DIR)


def _run_one(task: tuple[dict, int]) -> str:
    """Execute one discovery run and return its stopping state.

    The key is ``status:answer``.  Failing to answer is a valid stopping state and is
    recorded as such (``halted:`` or ``gave_up:``), because losing or gaining the
    ability to fail on a problem is exactly the kind of change the oracle should catch.
    """
    problem, seed = task
    runner = EngineRunner(_META)
    runner.init_mcat(
        problem["initial"],
        problem["modified"],
        problem["target"],
        seed=seed,
    )
    runner.run_mcat(max_steps=MAX_STEPS)
    ctx = runner.ctx
    answer = ctx.workspace.answer_string.text if ctx.workspace.answer_string else ""
    return f"{runner.status}:{answer}"


def _absence_check_states(counts: Counter, total: int) -> dict:
    """Smallest set of most-frequent states whose combined frequency reaches 50%."""
    chosen: list[str] = []
    cumulative = 0
    for state, n in counts.most_common():
        chosen.append(state)
        cumulative += n
        if cumulative / total >= 0.5:
            break
    return {
        "states": chosen,
        "cumulative_frequency": round(cumulative / total, 6),
        # Probability each listed state is absent from a 100-run check, if still
        # reachable at its baseline frequency. Small values mean absence is evidence.
        "absence_probability_at_n100": {
            s: round((1.0 - counts[s] / total) ** 100, 12) for s in chosen
        },
    }


def saturate(
    problem: dict,
    pool: Pool,
    prior: dict | None = None,
    verbose: bool = True,
) -> dict:
    """Sample a problem to saturation, resuming from ``prior`` if given.

    Resumption is exact rather than approximate: run *i* always uses seed *i*, so
    continuing from seed ``N`` produces precisely the sample a single uninterrupted
    run would have produced.
    """
    counts: Counter = Counter(prior["counts"]) if prior else Counter()
    total = prior["runs"] if prior else 0
    # States admitted by human review after being observed under a different execution
    # mode -- free-running, a different numeric backend -- rather than by this sampler.
    # Carried forward explicitly because ``expected_range`` is rebuilt from ``counts``
    # below, so anything not in ``counts`` would be silently dropped by a resume, and the
    # state would then present as a fresh regression the next time it appeared.
    admitted: dict = dict(prior.get("admitted_states", {})) if prior else {}
    first_seen: dict[str, int] = dict(prior["first_seen_at_run"]) if prior else {}
    started = time.perf_counter()
    prior_seconds = prior.get("seconds", 0.0) if prior else 0.0
    reason = "max_runs"
    if prior and verbose and total:
        print(f"    resuming from N={total} ({len(counts)} states already found)", flush=True)

    while total < MAX_RUNS:
        tasks = [(problem, s) for s in range(total, total + BATCH)]
        for i, state in enumerate(pool.map(_run_one, tasks, chunksize=25), start=total + 1):
            if state not in first_seen:
                first_seen[state] = i
            counts[state] += 1
        total += BATCH

        f1 = sum(1 for v in counts.values() if v == 1)
        ratio = f1 / total

        if verbose:
            print(
                f"    N={total:>6}  states={len(counts):>3}  f1={f1:>3}  "
                f"f1/N={ratio:.6f}",
                flush=True,
            )

        if total < MIN_RUNS:
            continue
        if f1 == 0:
            if total < MIN_RUNS_IF_NO_SINGLETONS:
                continue
            reason = "no_singletons"
            break
        if ratio <= TARGET_UPPER:
            reason = "in_band" if ratio > TARGET_LOWER else "overshot_below_band"
            break

    elapsed = time.perf_counter() - started
    f1 = sum(1 for v in counts.values() if v == 1)
    ratio = f1 / total

    return {
        "name": problem["name"],
        "demo_names": problem.get("demo_names", [problem["name"]]),
        "source_modes": sorted(problem.get("source_modes", {problem["mode"]})),
        "initial": problem["initial"],
        "modified": problem["modified"],
        "target": problem["target"],
        "runs": total,
        # The union of what this sampler found and what review has admitted.
        "distinct_states": len(set(counts) | set(admitted)),
        "f1": f1,
        "f1_over_n": round(ratio, 8),
        "stop_reason": reason,
        "saturated": reason != "max_runs",
        "expected_range": sorted(set(counts) | set(admitted)),
        "admitted_states": admitted,
        "counts": dict(counts.most_common()),
        "first_seen_at_run": {s: first_seen[s] for s, _ in counts.most_common()},
        "absence_check": _absence_check_states(counts, total),
        "seconds": round(prior_seconds + elapsed, 1),
    }


def _meets_criterion(record: dict) -> bool:
    """Does a stored record satisfy the criterion as it stands *now*?

    Checked on resume rather than trusting the stored ``saturated`` flag, so that
    tightening a threshold automatically re-opens the problems it affects instead of
    silently leaving an under-sampled baseline on disk.
    """
    if not record.get("saturated"):
        return False
    if record["f1"] == 0:
        return record["runs"] >= MIN_RUNS_IF_NO_SINGLETONS
    return record["f1_over_n"] <= TARGET_UPPER


def _write(path: str, results: list[dict], seconds: float, backend: str) -> None:
    """Serialise the baseline. Called after every problem so an interruption costs
    at most the problem in flight — the first version of this script wrote only at the
    end, and a mid-run stop threw away everything."""
    results = sorted(results, key=lambda r: (r["initial"], r["modified"], r["target"]))
    payload = {
        "generated_by": "scripts/build_expected_range.py",
        "criterion": {
            "statistic": "good_turing_missing_mass (f1/N)",
            "target_upper": TARGET_UPPER,
            "target_lower": TARGET_LOWER,
            "min_runs": MIN_RUNS,
            "max_runs": MAX_RUNS,
            "batch": BATCH,
            "max_steps_per_run": MAX_STEPS,
            "numeric_backend": backend,
        },
        "scope": (
            "Every unique (initial, modified, target) triple across all demo problems, "
            "run in discovery mode. Demos catalogued as justification contribute their "
            "triple with the supplied answer dropped: justification MODE is not carried "
            "forward past Phase 0, but the underlying analogy problems are."
        ),
        "note": (
            "Regression oracle: compare SET MEMBERSHIP, never frequencies. A stopping "
            "state outside expected_range is a strong signal to investigate, not an "
            "automatic failure — see f1_over_n for the per-problem false-alarm rate. "
            "Absence is only evidence for the states listed in absence_check. "
            "expected_range is the union of the serially-saturated sample and any states "
            "in admitted_states, which were observed under a different execution mode "
            "and accepted by human review. The counts, f1 and f1_over_n fields describe "
            "the serial saturation sample ONLY and are deliberately not adjusted when a "
            "state is admitted: they measure how completely that sample explored, which "
            "admitting a state from elsewhere does not change."
        ),
        "totals": {
            "problems": len(results),
            "runs": sum(r["runs"] for r in results),
            "seconds": round(seconds, 1),
        },
        "problems": results,
    }
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(payload, fh, indent=2)
        fh.write("\n")
    os.replace(tmp, path)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 4) - 1))
    ap.add_argument("--problem", default=None, help="run a single problem by demo name")
    ap.add_argument("--force", action="store_true",
                    help="resample problems already recorded as saturated")
    ap.add_argument("--backend", default=None,
                    help="numeric backend for every worker (default: the first of "
                         f"{'/'.join(DEFAULT_BACKENDS)} that is installed)")
    args = ap.parse_args()

    backend = args.backend or resolve_backend(DEFAULT_BACKENDS)
    if args.backend and os.path.abspath(args.out) == os.path.abspath(DEFAULT_OUT):
        sys.exit(
            f"--backend {args.backend} writes a sample from a chosen backend, and "
            f"{DEFAULT_OUT} holds the float64 reference sample. Pass --out to write "
            f"it somewhere else, and compare the two."
        )

    with open(os.path.join(SEED_DIR, "demo_problems.json")) as fh:
        all_problems = json.load(fh)

    # Discovery mode only. Justification mode is not carried forward past Phase 0, so
    # baselining it would freeze behaviour we intend to retire. It is also a poor fit
    # for this oracle: the answer is supplied rather than discovered, so the reachable
    # set collapses to a couple of statuses and says little about perception.
    # Every demo contributes its analogy problem, regardless of the mode it was
    # catalogued under. A justification demo supplies an answer; that answer is simply
    # dropped and the underlying (initial, modified, target) triple is run in discovery
    # mode. Justification *mode* is not carried forward past Phase 0, but the problems
    # are perfectly good letter analogies and excluding them would shrink the baseline
    # for no reason.
    #
    # Many demos share a triple under different names — abc->abd; xyz? appears seven
    # times across both modes. The reachable set depends only on the triple, so each is
    # baselined once with every contributing demo name recorded.
    by_triple: dict[tuple, dict] = {}
    for p in all_problems:
        key = (p["initial"], p["modified"], p["target"])
        if key in by_triple:
            by_triple[key]["demo_names"].append(p["name"])
            by_triple[key]["source_modes"].add(p["mode"])
        else:
            by_triple[key] = {**p, "demo_names": [p["name"]], "source_modes": {p["mode"]}}
    problems = list(by_triple.values())
    deduped = len(all_problems) - len(problems)
    if args.problem:
        problems = [p for p in problems if args.problem in p["demo_names"]]
        if not problems:
            sys.exit(f"no demo problem named {args.problem!r}")

    print(
        f"Building expected-range baseline: {len(problems)} distinct analogy problems "
        f"from {len(all_problems)} demos ({deduped} duplicate triples merged), "
        f"{args.workers} workers on the {backend} backend, "
        f"band {TARGET_LOWER} < f1/N <= {TARGET_UPPER}",
        flush=True,
    )

    # Resume: load anything already recorded so a re-run appends rather than restarts.
    prior_by_triple: dict[tuple, dict] = {}
    if os.path.exists(args.out):
        with open(args.out) as fh:
            existing = json.load(fh)
        for rec in existing.get("problems", []):
            prior_by_triple[(rec["initial"], rec["modified"], rec["target"])] = rec
        print(f"Resuming from {args.out}: {len(prior_by_triple)} problem(s) on file", flush=True)

    results: list[dict] = []
    overall = time.perf_counter()

    def flush_to_disk() -> list[dict]:
        """Write the union of this session's results and everything already on file.

        Called after every problem, so an interruption costs at most the problem in
        flight. Crucially it *merges* rather than replaces: running a single problem
        with ``--problem`` appends to the baseline instead of truncating it to one
        entry. New problems can therefore be added to the pool and sampled one at a
        time, accumulating into the same file.
        """
        touched = {(x["initial"], x["modified"], x["target"]) for x in results}
        merged = results + [r for k, r in prior_by_triple.items() if k not in touched]
        _write(args.out, merged, time.perf_counter() - overall, backend)
        return sorted(merged, key=lambda r: (r["initial"], r["modified"], r["target"]))

    with Pool(args.workers, initializer=_init_worker, initargs=(backend,)) as pool:
        for idx, problem in enumerate(problems, 1):
            key = (problem["initial"], problem["modified"], problem["target"])
            arrow = f"{problem['initial']}->{problem['modified']}; {problem['target']}?"
            names = "/".join(problem["demo_names"])
            prior = prior_by_triple.get(key)

            if prior and _meets_criterion(prior) and not args.force:
                # Refresh the demo names in case the catalogue changed, but do not resample.
                prior["demo_names"] = problem["demo_names"]
                prior["source_modes"] = sorted(problem.get("source_modes", set()))
                results.append(prior)
                print(
                    f"\n[{idx}/{len(problems)}] {names}  {arrow}\n"
                    f"    -> already saturated ({prior['distinct_states']} states in "
                    f"{prior['runs']} runs); skipping",
                    flush=True,
                )
                continue

            print(f"\n[{idx}/{len(problems)}] {names}  {arrow}", flush=True)
            record = saturate(problem, pool, prior=None if args.force else prior)
            results.append(record)
            print(
                f"    -> {record['distinct_states']} states in {record['runs']} runs "
                f"({record['stop_reason']}, {record['seconds']}s); "
                f"absence-check on {len(record['absence_check']['states'])} state(s) "
                f"covering {record['absence_check']['cumulative_frequency']:.0%}",
                flush=True,
            )
            flush_to_disk()

    on_file = flush_to_disk()
    print(
        f"\nWrote {args.out}\n"
        f"  {len(on_file)} problems on file, {sum(r['runs'] for r in on_file):,} runs "
        f"total ({len(results)} touched this session, "
        f"{time.perf_counter() - overall:.0f}s)",
        flush=True,
    )
    unsaturated = [r["name"] for r in on_file if not r["saturated"]]
    if unsaturated:
        print(f"  NOT SATURATED (hit max_runs): {unsaturated}", flush=True)


if __name__ == "__main__":
    main()
