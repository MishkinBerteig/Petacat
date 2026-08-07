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
             the single-run sets. A run that hits the working cap is re-run at
             the reference's own cap and compared on what it reaches there, so
             no single-run state is reported that the two caps make
             incomparable. See MAX_STEPS.
  episodic   100 episodes of 8 runs per problem, memory carried forward within
             an episode, against the convergence sets. An episode's convergence
             answer is its last run that produced an answer; *NONE* and *CAP*
             are skipped looking backwards. Capped runs are NOT re-run here --
             memory carries forward, so there is no such thing as re-running one
             run of an episode. See MAX_STEPS.

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

# The working cap, and the reference's. Sampling at 20,000 is what makes a cycle
# cheap enough to run often; the reference sampled at 100,000, so a *CAP* at
# 20,000 may be a run that would have answered given the reference's budget.
#
# SINGLE RUNS RESOLVE THAT, rather than reporting a state the comparison knows is
# not comparable. A single run is independent -- fresh memory, one seed -- so
# re-running it at REFERENCE_MAX_STEPS is the same run continued, and whatever it
# reaches there is what gets compared. It is cheap because caps are rare: 23 of
# 1,900 in a cycle, 22 of them on misc3, where the reference *also* caps (10.96%
# of 19,000 runs) and *CAP* is a member of the reference set in its own right.
#
# EPISODES DO NOT, for two reasons. Memory carries forward, so a run resolved at
# a higher cap would have added an answer the rest of the episode never saw --
# re-running one run does not give the episode that would have happened, and
# re-running the whole episode is a different measurement, not a resolution of
# this one. And it is not needed: capping is what an exhausted session *does* in
# both programs, because answers.ss:982 refuses an answer already stored. The
# reference caps in 9,928 of its 76,000 episodic runs (13.1%) at 100,000, on the
# same problems, and 16.8% of its episodic runs pass 20,000 codelets -- against
# 15.8% capped here. The two modes agree in shape; single runs are where the cap
# shows, and that is where it is resolved.
MAX_STEPS = 20_000
REFERENCE_MAX_STEPS = 100_000

_META = None
_BACKEND = "numpy"


def _init(backend: str) -> None:
    global _META
    os.environ["PETACAT_NUMERIC_BACKEND"] = backend
    from server.engine.metadata import MetadataProvider
    _META = MetadataProvider.from_seed_data(SEED_DIR)


def _state(runner, ctx, answered: bool, cap: int = MAX_STEPS) -> str:
    from server.engine.runner import STATUS_ANSWER_FOUND
    if answered and runner.status == STATUS_ANSWER_FOUND:
        return ctx.workspace.answer_string.text if ctx.workspace.answer_string else "*NONE*"
    if ctx.codelet_count >= cap:
        return "*CAP*"
    return "*NONE*"


def _one_run(problem, seed, cap):
    from server.engine.runner import EngineRunner, STATUS_ANSWER_FOUND

    runner = EngineRunner(_META)
    runner.init_mcat(*problem, seed=seed)
    runner.run_mcat(max_steps=cap)
    state = _state(runner, runner.ctx, runner.status == STATUS_ANSWER_FOUND, cap)
    return state, runner.ctx.codelet_count


def run_single(task):
    """One run from a fresh memory -- the single-run mode.

    Returns ``(state, resolved)``, where *resolved* is ``None`` unless the run hit
    MAX_STEPS and was re-run at the reference's cap, in which case it is
    ``(state_at_20k, codelets)`` from that longer run -- reported, not hidden.
    """
    problem, seed = task
    state, _ = _one_run(problem, seed, MAX_STEPS)
    if state != "*CAP*":
        return state, None
    resolved, codelets = _one_run(problem, seed, REFERENCE_MAX_STEPS)
    return resolved, (seed, codelets)


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


def compare(name, produced: Counter, ref_set: dict, ref_p50: dict, n: int,
            also_reached: set | None = None):
    """One problem's two flags, plus what the reference reaches elsewhere.

    *also_reached* is the reference's **single-run** set, passed when comparing
    episodes. A convergence answer outside the convergence set but inside that
    one is not something the reference cannot do -- it is something the
    reference does, and did not happen to do as the convergence answer of one of
    its 500 sampled episodes. Those sets are deliberately unsaturated
    (``f1_over_n`` up to 0.0160), so that is the expected case rather than a
    finding, and separating the two is what leaves the second list worth reading:
    of one cycle's 28 novel episodes, 12 were of the first kind.
    """
    members = set(ref_set["set"])
    p50 = [e["member"] for e in ref_p50["p50"]]
    missing = [m for m in p50 if produced[m] == 0]
    novel = sorted(m for m in produced if m not in members)
    entries = []
    for m in novel:
        entry = {"member": m, "count": produced[m]}
        if also_reached is not None:
            entry["in_single_run_set"] = m in also_reached
        entries.append(entry)
    return {
        "problem": name,
        "n": n,
        "reference_f1_over_n": ref_set["f1_over_n"],
        "missing_p50": missing,
        "novel": entries,
        "produced": dict(produced.most_common()),
        "reference_p50": p50,
    }


def mark_recurrences(rows, previous, mode):
    """Flag every novel member the previous cycle also produced.

    A member that recurs across cycles is not missing mass, whatever its count in
    one of them -- the Good-Turing argument that excuses a singleton is an
    argument about *one* sample. Comparing by hand needs someone to remember the
    last cycle; this reads it off the file the last cycle wrote.
    """
    if not previous:
        return
    before = {r["problem"]: {e["member"] for e in r["novel"]}
              for r in previous.get(mode, [])}
    for row in rows:
        seen = before.get(row["problem"], set())
        for entry in row["novel"]:
            entry["also_last_cycle"] = entry["member"] in seen


def _label(entry):
    """``member x count``, marked ``+`` when the previous cycle produced it too."""
    mark = "+" if entry.get("also_last_cycle") else ""
    return f"{entry['member']}x{entry['count']}{mark}"


def report(title, rows, note=""):
    print(f"\n{'=' * 78}\n{title}\n{'=' * 78}")
    if note:
        print(note + "\n")
    print(f"{'problem':12s} {'distinct':>8} {'MISSING p50':>32}  NOVEL")
    n_missing = n_novel = 0
    # Split only where the episodic comparison filled the field in.
    weak = [e for r in rows for e in r["novel"] if e.get("in_single_run_set")]
    for r in rows:
        miss = ", ".join(r["missing_p50"]) if r["missing_p50"] else "-"
        strong = [e for e in r["novel"] if not e.get("in_single_run_set")]
        nov = ", ".join(_label(e) for e in strong) or "-"
        n_missing += len(r["missing_p50"])
        n_novel += len(strong)
        print(f"{r['problem']:12s} {len(r['produced']):>8} {miss:>32}  {nov}")
    print(f"\n{n_missing} missing p50 across {len(rows)} problems; "
          f"{n_novel} novel members.")
    if weak:
        print(f"\n{len(weak)} further member(s) are outside the convergence set but "
              f"INSIDE the reference's\nsaturated single-run set — answers the "
              f"reference reaches, just not as the convergence\nanswer of one of "
              f"its 500 episodes. Expected, at the rate f1/n gives:")
        for r in rows:
            ws = [e for e in r["novel"] if e.get("in_single_run_set")]
            if ws:
                print(f"  {r['problem']:12s} {', '.join(_label(e) for e in ws)}")
    recurring = [(r["problem"], e) for r in rows for e in r["novel"]
                 if e.get("also_last_cycle")]
    if recurring:
        print(f"\n+ marks {len(recurring)} member(s) the previous cycle produced too. "
              f"A member that\nrecurs across cycles is not missing mass, whatever "
              f"its count in one of them.")
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
           "max_steps": MAX_STEPS,
           "reference_max_steps": REFERENCE_MAX_STEPS,
           "backend": args.backend,
           "start_seed": args.start_seed,
           "reference": os.path.relpath(DERIVED, ROOT)}

    with Pool(processes=args.jobs, initializer=_init,
              initargs=(args.backend,)) as pool:
        if args.mode in ("single", "both"):
            rows = []
            for name in names:
                p = tuple(s_sets[name]["problem"][1:])
                results = pool.map(
                    run_single,
                    [(p, args.start_seed + i) for i in range(args.tries)],
                    chunksize=1)
                got = Counter(state for state, _ in results)
                row = compare(name, got, s_sets[name], s_p50[name], args.tries)
                # Runs that hit MAX_STEPS and were re-run at the reference's cap.
                # Recorded rather than folded away: the state being compared came
                # from a longer run than every other state in this row.
                row["resolved_at_reference_cap"] = [
                    {"seed": seed, "codelets": codelets, "state": state}
                    for state, resolved in results if resolved
                    for seed, codelets in [resolved]
                ]
                rows.append(row)
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
                row = compare(name, got, c_sets[name], c_p50[name], args.tries,
                              also_reached=set(s_sets[name]["set"]))
                row["episodes_never_answering"] = args.tries - len(finals)
                row["sequences"] = seqs
                rows.append(row)
                print(f"  episodic {name:12s} done", flush=True)
            out["episodic"] = rows

    # Before overwriting it, read what the previous cycle produced, so a novel
    # member that recurs is visible without anyone remembering.
    out_path = os.path.join(ROOT, args.out)
    previous = None
    if os.path.exists(out_path):
        try:
            with open(out_path) as fh:
                previous = json.load(fh)
        except (OSError, ValueError):
            previous = None
    for mode in ("single", "episodic"):
        if mode in out:
            mark_recurrences(out[mode], previous, mode)

    os.makedirs(os.path.join(ROOT, os.path.dirname(args.out)), exist_ok=True)
    with open(out_path, "w") as fh:
        json.dump(out, fh, indent=2)

    if "single" in out:
        report(f"SINGLE RUNS — {args.tries} runs per problem", out["single"],
               "Reference sets are saturated, so a novel state is a strong signal.")
        resolved = [(r["problem"], e) for r in out["single"]
                    for e in r["resolved_at_reference_cap"]]
        if resolved:
            print(f"\n{len(resolved)} run(s) hit the {MAX_STEPS:,}-codelet cap and were "
                  f"re-run at the reference's {REFERENCE_MAX_STEPS:,}:")
            for problem, e in resolved:
                print(f"  {problem:12s} seed {e['seed']}  ->  {e['state']}"
                      f"  at {e['codelets']:,} codelets")
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
