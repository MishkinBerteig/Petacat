#!/usr/bin/env python3
"""
Compare Petacat against Metacat's measured reference data.

    scripts/compare_to_metacat.py                    both modes, all problems
    scripts/compare_to_metacat.py --mode single
    scripts/compare_to_metacat.py --only misc1,run6 -n 100

Petacat never generates oracle data. It runs a short sample and compares it
against the sets Metacat published; see ../Metacat/ORACLE-USAGE.md for the
protocol this implements.

TWO MODES, TWO CHECKS EACH, AND NOTHING FAILS

  single     100 runs per problem, each from a fresh Episodic Memory, against
             the single-run sets.
  episodic   100 episodes of 8 runs per problem, memory carried forward within
             an episode, against the convergence sets. An episode's convergence
             answer is its last run that produced an answer; *NONE* and *CAP*
             are skipped looking backwards.

  MISSING    a p50 member of the reference set that Petacat did not produce.
  NOVEL      something Petacat produced that the reference never did.

Both are FLAGS. Metacat is stochastic and self-watching with no ground truth, so
this says stable or changed, never pass or fail. Every novel result is reported
with the reference's own f1/n, which is the rate at which the reference would
produce an unseen member itself -- on the convergence sets that is deliberately
non-zero, so roughly eight novel answers per cycle are expected even from a
perfect port.

WHAT THIS DOES NOT DO. It draws no conclusion about whether Petacat is a faithful
port. It reports what differs.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from multiprocessing import Pool

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SEED_DIR = os.path.join(ROOT, "seed_data")
METACAT = os.path.join(os.path.dirname(ROOT), "Metacat")
DERIVED = os.path.join(METACAT, "oracle", "derived")

ANSWERLESS = {"*NONE*", "*CAP*"}

# Petacat's cap. Metacat sampled at 100,000; a lower cap here can only turn a
# would-be answer into *CAP*, so it is reported alongside the flags rather than
# hidden.
MAX_STEPS = 20_000

_META = None
_BACKEND = "numpy"


def _init(backend: str) -> None:
    global _META
    os.environ["PETACAT_NUMERIC_BACKEND"] = backend
    from server.engine.metadata import MetadataProvider
    _META = MetadataProvider.from_seed_data(SEED_DIR)


def _state(runner, ctx, answered: bool) -> str:
    from server.engine.runner import STATUS_ANSWER_FOUND
    if answered and runner.status == STATUS_ANSWER_FOUND:
        return ctx.workspace.answer_string.text if ctx.workspace.answer_string else "*NONE*"
    if ctx.codelet_count >= MAX_STEPS:
        return "*CAP*"
    return "*NONE*"


def run_single(task):
    """One run from a fresh memory -- the single-run mode."""
    problem, seed = task
    from server.engine.runner import EngineRunner, STATUS_ANSWER_FOUND

    runner = EngineRunner(_META)
    runner.init_mcat(*problem, seed=seed)
    runner.run_mcat(max_steps=MAX_STEPS)
    ctx = runner.ctx
    return _state(runner, ctx, runner.status == STATUS_ANSWER_FOUND)


def run_episode(task):
    """Eight runs sharing one memory; returns the ordered states."""
    problem, start_seed, runs = task
    from server.engine.memory import EpisodicMemory
    from server.engine.runner import EngineRunner, STATUS_ANSWER_FOUND

    memory = EpisodicMemory()
    states = []
    for i in range(runs):
        # A run "answered" only if it ADDED one. init_mcat keeps the memory and
        # only clears activations (run.ss:212), so memory is non-empty from run 1
        # and its emptiness cannot be the test -- the same trap Metacat's harness
        # has, where give-up also reports success.
        before = len(memory.answers)
        runner = EngineRunner(_META)
        runner.init_mcat(*problem, seed=start_seed + i, memory=memory)
        runner.run_mcat(max_steps=MAX_STEPS)
        answered = (len(memory.answers) > before
                    and runner.status == STATUS_ANSWER_FOUND)
        states.append(_state(runner, runner.ctx, answered))
    return states


def convergence_answer(states):
    for s in reversed(states):
        if s not in ANSWERLESS:
            return s
    return None


def load(name):
    with open(os.path.join(DERIVED, name)) as fh:
        return {r["name"]: r for r in json.load(fh)["results"]}


def compare(name, produced: Counter, ref_set: dict, ref_p50: dict, n: int):
    members = set(ref_set["set"])
    p50 = [e["member"] for e in ref_p50["p50"]]
    missing = [m for m in p50 if produced[m] == 0]
    novel = sorted(m for m in produced if m not in members)
    return {
        "problem": name,
        "n": n,
        "reference_f1_over_n": ref_set["f1_over_n"],
        "missing_p50": missing,
        "novel": [{"member": m, "count": produced[m]} for m in novel],
        "produced": dict(produced.most_common()),
        "reference_p50": p50,
    }


def report(title, rows, note=""):
    print(f"\n{'=' * 78}\n{title}\n{'=' * 78}")
    if note:
        print(note + "\n")
    print(f"{'problem':12s} {'distinct':>8} {'MISSING p50':>32}  NOVEL")
    n_missing = n_novel = 0
    for r in rows:
        miss = ", ".join(r["missing_p50"]) if r["missing_p50"] else "-"
        nov = ", ".join(f"{e['member']}x{e['count']}" for e in r["novel"]) or "-"
        n_missing += len(r["missing_p50"])
        n_novel += len(r["novel"])
        print(f"{r['problem']:12s} {len(r['produced']):>8} {miss:>32}  {nov}")
    print(f"\n{n_missing} missing p50 across {len(rows)} problems; "
          f"{n_novel} novel members.")
    return n_missing, n_novel


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["single", "episodic", "both"],
                    default="both")
    ap.add_argument("-n", "--tries", type=int, default=100,
                    help="runs per problem, or episodes per problem")
    ap.add_argument("-r", "--runs", type=int, default=8,
                    help="runs per episode")
    ap.add_argument("--start-seed", type=int, default=900_000,
                    help="clear of both Metacat data sets by default")
    ap.add_argument("--backend", default="numpy")
    ap.add_argument("-j", "--jobs", type=int, default=8)
    ap.add_argument("--only")
    ap.add_argument("-o", "--out", default="measurements/vs-metacat.json")
    args = ap.parse_args()

    s_sets, s_p50 = load("single-run-sets.json"), load("single-run-p50.json")
    c_sets, c_p50 = load("convergence-sets.json"), load("convergence-p50.json")

    names = list(s_sets)
    if args.only:
        wanted = set(args.only.split(","))
        names = [n for n in names if n in wanted]

    out = {"tries_per_problem": args.tries, "runs_per_episode": args.runs,
           "max_steps": MAX_STEPS, "backend": args.backend,
           "start_seed": args.start_seed,
           "reference": os.path.relpath(DERIVED, ROOT)}

    with Pool(processes=args.jobs, initializer=_init,
              initargs=(args.backend,)) as pool:
        if args.mode in ("single", "both"):
            rows = []
            for name in names:
                p = tuple(s_sets[name]["problem"][1:])
                got = Counter(pool.map(
                    run_single,
                    [(p, args.start_seed + i) for i in range(args.tries)],
                    chunksize=1))
                rows.append(compare(name, got, s_sets[name], s_p50[name],
                                    args.tries))
                print(f"  single   {name:12s} done", flush=True)
            out["single"] = rows

        if args.mode in ("episodic", "both"):
            rows = []
            for name in names:
                p = tuple(c_sets[name]["problem"][1:])
                seqs = pool.map(
                    run_episode,
                    [(p, args.start_seed + e * args.runs, args.runs)
                     for e in range(args.tries)],
                    chunksize=1)
                finals = [a for a in (convergence_answer(s) for s in seqs)
                          if a is not None]
                got = Counter(finals)
                row = compare(name, got, c_sets[name], c_p50[name], args.tries)
                row["episodes_never_answering"] = args.tries - len(finals)
                row["sequences"] = seqs
                rows.append(row)
                print(f"  episodic {name:12s} done", flush=True)
            out["episodic"] = rows

    os.makedirs(os.path.join(ROOT, os.path.dirname(args.out)), exist_ok=True)
    with open(os.path.join(ROOT, args.out), "w") as fh:
        json.dump(out, fh, indent=2)

    if "single" in out:
        report(f"SINGLE RUNS — {args.tries} runs per problem", out["single"],
               "Reference sets are saturated, so a novel state is a strong signal.")
    if "episodic" in out:
        report(f"EPISODES — {args.tries} episodes of {args.runs} runs",
               out["episodic"],
               "Convergence sets are deliberately unsaturated: ~8 novel answers\n"
               "across the 19 problems are expected even from a perfect port.")
    print(f"\nfull results -> {args.out}")
    # Flags are not failures. Always exits 0.
    return 0


if __name__ == "__main__":
    sys.exit(main())
