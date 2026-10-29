#!/usr/bin/env python3
"""The fidelity "widened net": record Metacat on many unlike problems and replay them in Petacat.

Reproduces the 2026-10-29 pass that looked for lockstep desynchronisations beyond the 19-problem
corpus.  Three nets, each a problem list in ``tests/lockstep/data/``:

=========  ===========================  ==========  =====  ====================================
net        list                         seeds       cap    runs
=========  ===========================  ==========  =====  ====================================
widen      ``fidelity_widen.txt`` (48)  1-10        4000   480 single runs
widen2     ``fidelity_widen2.txt`` (36) 1-5         4000   180 single runs (widen + widen2: 660)
episodes   ``fidelity_episodes.txt`` (8) 1-3         5000   24 episodes of 8 runs (192 runs)
=========  ===========================  ==========  =====  ====================================

Stages (each resumable; existing traces are kept):

1. ``record`` -- ``tests/lockstep/metacat/record.py`` per problem (snapshots on, so a state
   difference that has not yet changed a decision shows), one container per run;
2. ``replay`` -- ``scripts/lockstep_corpus.py`` replays every trace in Petacat and prints a row
   per trace (reach, run length, agreement, unregistered errors, differing state snapshots);
3. ``answers`` (episodes net only) -- ``scripts/compare_episode_answers.py``: Metacat's
   explanation of every answer in memory and comparison of every pair, against Petacat's,
   order-sensitive unless ``--ignore-order``.

    scripts/sweep_fidelity.py --net widen --limit 1 --seeds 1-5         # smoke test
    scripts/sweep_fidelity.py --net widen2                                # about 1 h
    scripts/sweep_fidelity.py --net all --jobs 3                          # the whole net: hours

Reported result of the original pass: all 660 single runs and all 192 episode runs replay to
their end with 0 errors and 0 differing snapshots.  The full net takes hours and is the user's
call to repeat; ``--limit`` and ``--seeds`` give a short slice.  Outputs go under ``--out``
(default ``tests/lockstep/out/fidelity``, git-ignored).  Exit status 1 if any run falls short.
"""

from __future__ import annotations

import argparse
import collections
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests" / "lockstep" / "metacat"))
sys.path.insert(0, str(ROOT / "scripts"))

import wrap  # noqa: E402

DATA = ROOT / "tests" / "lockstep" / "data"
#: net -> (problem list, seeds, cap, runs per episode (0 = single runs))
NETS = {
    "widen": ("fidelity_widen.txt", "1-10", 4000, 0),
    "widen2": ("fidelity_widen2.txt", "1-5", 4000, 0),
    "episodes": ("fidelity_episodes.txt", "1-3", 5000, 8),
}
ROW = re.compile(r"^(\S+)\s+(\S+)\s+(\d+)\s+(\d+)\s+([\d.]+)\s+(\d+)\s+(\d+)\s+(.*)$")
RECORD_LINE = re.compile(r"^seed (\d+): (\S+) (\d+) codelets")


def parse_table(text: str) -> list[dict]:
    """Rows of ``lockstep_corpus.py``'s table: problem, seed, reach, length, agreement,
    unregistered errors, differing state snapshots, first fatal."""
    rows = []
    for line in text.splitlines():
        m = ROW.match(line)
        if m and not line.startswith("problem"):
            rows.append({"problem": m[1], "seed": m[2], "reach": int(m[3]), "length": int(m[4]),
                         "agreement": float(m[5]), "errors": int(m[6]), "snaps": int(m[7]),
                         "fatal": m[8].strip()})
    return rows


def short_rows(rows: list[dict]) -> list[dict]:
    """Rows that did not replay cleanly: stopped short of the run, errors, or differing snapshots."""
    return [r for r in rows if r["reach"] < r["length"] or r["errors"] > 0 or r["snaps"] > 0]


def parse_record_log(text: str) -> dict:
    """``record.py``'s per-seed lines -> ``{seed: (outcome, codelets)}`` (single-run mode)."""
    out = {}
    for line in text.splitlines():
        m = RECORD_LINE.match(line)
        if m:
            out[int(m[1])] = (m[2], int(m[3]))
    return out


def outcome_tally(logs: dict) -> collections.Counter:
    """Count of each outcome (answer, ``*NONE*`` for a give-up, ``*CAP*``) over ``parse_record_log`` results."""
    return collections.Counter(o for o, _ in logs.values())


def record(problem: list[str], seeds: str, cap: int, runs: int, root: Path, jobs: int) -> str:
    """Stage 1 for one problem; returns record.py's log (also saved under ``root/logs``)."""
    slug = "-".join(problem)
    log = root / "logs" / f"{slug}.log"
    if log.exists():
        return log.read_text(encoding="utf-8")
    cmd = [sys.executable, str(ROOT / "tests" / "lockstep" / "metacat" / "record.py"),
           "--problem", *problem, "--seeds", seeds, "--cap", str(cap), "--out", str(root / "traces"),
           "--jobs", str(jobs)]
    if runs:
        cmd += ["--episode-runs", str(runs)]
    done = subprocess.run(cmd, capture_output=True, text=True)
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text(done.stdout + done.stderr, encoding="utf-8")
    return done.stdout


def replay(root: Path, episodes: bool, jobs: int, problems: list[str]) -> str:
    """Stage 2: ``lockstep_corpus.py`` over the net's traces; returns its table."""
    cmd = [sys.executable, str(ROOT / "scripts" / "lockstep_corpus.py"), "--traces", str(root / "traces"),
           "--out-dir", str(root / "replay"), "--jobs", str(jobs)]
    if episodes:
        cmd.append("--episodes")
    for p in problems:
        cmd += ["--problem", p]
    done = subprocess.run(cmd, capture_output=True, text=True)
    (root / "replay.log").write_text(done.stdout + done.stderr, encoding="utf-8")
    return done.stdout


def run_net(name: str, args) -> int:
    listfile, seeds, cap, runs = NETS[name]
    seeds = args.seeds or seeds
    problems = wrap.read_problem_list(args.problems or DATA / listfile)
    if args.limit:
        problems = problems[: args.limit]
    root = Path(args.out) / name
    slugs = ["-".join(p) for p in problems]
    print(f"== net {name}: {len(problems)} problems, seeds {seeds}, cap {cap}"
          + (f", episodes of {runs} runs" if runs else ""), flush=True)
    failed = 0
    if args.stage in ("record", "all"):
        tally: collections.Counter = collections.Counter()
        for p in problems:
            log = record(p, seeds, cap, runs, root, args.jobs)
            if not runs:
                answers = parse_record_log(log)
                tally.update(o for o, _ in answers.values())
                print(f"{'-'.join(p)}: " + " ".join(f"{o}x{n}" for o, n in
                                                    collections.Counter(o for o, _ in answers.values()).most_common()), flush=True)
        if tally:
            print("outcomes:", dict(tally))
    if args.stage in ("replay", "all"):
        rows = parse_table(replay(root, bool(runs), args.jobs, slugs))
        bad = short_rows(rows)
        failed += len(bad)
        print(f"replayed {len(rows)} traces: {len(rows) - len(bad)} reach their end with no unregistered "
              f"error and no differing snapshot, {len(bad)} do not")
        for r in bad[:20]:
            print("  ", r)
    if runs and args.stage in ("answers", "all"):
        import compare_episode_answers as cea
        first = int(seeds.split("-")[0])
        last = int(seeds.split("-")[-1])
        bad_eps = 0
        for slug in slugs:
            for s in range(first, last + 1):
                r = cea.check_episode(slug, s, root / "traces", cap, args.ignore_order, runs)
                if not r["ok"]:
                    bad_eps += 1
                    print(f"DIFF {slug} episode {s}")
                    for p in r["problems"][:4]:
                        print("  " + p.replace("\n", "\n  "))
        print(f"answer check: {bad_eps} episodes differ ({'order ignored' if args.ignore_order else 'order-sensitive'})")
        failed += bad_eps
    return failed


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--net", choices=[*NETS, "all"], required=True)
    ap.add_argument("--stage", choices=("record", "replay", "answers", "all"), default="all")
    ap.add_argument("--problems", help="use this problem list file instead of the net's own")
    ap.add_argument("--limit", type=int, help="only the first N problems of each list")
    ap.add_argument("--seeds", help="override the net's seeds (episode seeds for the episodes net)")
    ap.add_argument("--jobs", type=int, default=3, help="Docker containers / replay workers at once (default 3)")
    ap.add_argument("--ignore-order", action="store_true", help="answer check: do not require Metacat's answer order")
    ap.add_argument("--out", default=str(wrap.DEFAULT_OUT / "fidelity"))
    args = ap.parse_args(argv)
    names = list(NETS) if args.net == "all" else [args.net]
    failed = sum(run_net(n, args) for n in names)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
