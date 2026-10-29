#!/usr/bin/env python3
"""The snag sweep: Metacat's snag explanations and commentary over many problems.

Reproduces the 2026-10-29 sweep that checked Petacat's snag text beyond the lockstep corpus
(28 problems with snags, 479 snags, 53 SWAP and 29 CONFLICT, all but one matched exactly;
the one replay desynchronisation was fixed afterwards).  Three stages, each resumable:

1. ``search``  -- ``tests/lockstep/metacat/record_snags.py`` on every problem of the list,
   seeds 1-12, cap 6000 (Docker, a few seconds per problem); keeps the problems that hit a snag;
2. ``record``  -- ``tests/lockstep/metacat/record.py --no-snapshots`` for those problems
   (the decision traces Petacat replays; about 10-40 MB raw each, a few GB for the full list);
3. ``compare`` -- replay each trace in Petacat and compare snags and comments with stage 1
   (``scripts/compare_snags.py``'s rules).

    scripts/sweep_snags.py --limit 3                       # smoke: first three problems
    scripts/sweep_snags.py --only-known --stage all        # the 28 problems that had snags
    scripts/sweep_snags.py --problems tests/lockstep/data/snag_sweep_problems.txt --jobs 3

The full sweep takes a long time (about 90 problems; the search alone is minutes, the
recording and replay of the 28 snag problems about an hour on an M-series Mac); it is the
user's decision to run it, and nothing in the test suite does.  Outputs go under ``--out``
(default ``tests/lockstep/out/snag-sweep``, git-ignored).  Exit status 1 if any snag differs.
"""

from __future__ import annotations

import argparse
import collections
import concurrent.futures
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests" / "lockstep" / "metacat"))
sys.path.insert(0, str(ROOT / "scripts"))

import compare_snags  # noqa: E402
import record_snags  # noqa: E402
import wrap  # noqa: E402

DATA = ROOT / "tests" / "lockstep" / "data"
SEEDS = "1-12"
CAP = 6000


def slug(problem: list[str]) -> str:
    return "-".join(problem)


def search_problem(problem: list[str], seeds: list[int], cap: int, out: Path) -> Path:
    """Stage 1 for one problem: Metacat's SNAG/CMT/END lines saved to ``out/search/<slug>.tsv``."""
    path = out / "search" / f"{slug(problem)}.tsv"
    if not path.exists():
        lines = record_snags.record(problem, seeds, cap)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def has_snag(path: Path) -> bool:
    return any(l.startswith("SNAG\t") for l in path.read_text(encoding="utf-8").splitlines())


def record_traces(problem: list[str], seeds: str, cap: int, out: Path, jobs: int) -> None:
    """Stage 2 for one problem: ``record.py`` traces (no snapshots) under ``out/traces``."""
    first = out / "traces" / slug(problem) / f"{wrap.parse_seeds(seeds)[0]}.metacat.jsonl.gz"
    if first.exists():
        return
    cmd = [sys.executable, str(ROOT / "tests" / "lockstep" / "metacat" / "record.py"),
           "--problem", *problem, "--seeds", seeds, "--cap", str(cap),
           "--out", str(out / "traces"), "--no-snapshots", "--jobs", str(jobs)]
    done = subprocess.run(cmd, capture_output=True, text=True)
    if done.returncode != 0:
        print(f"record.py failed for {slug(problem)}:\n{done.stdout[-500:]}{done.stderr[-500:]}", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--problems", default=str(DATA / "snag_sweep_problems.txt"), help="problem list file")
    ap.add_argument("--only-known", action="store_true",
                    help="use data/snag_sweep_with_snags.txt (the 28 problems that had snags)")
    ap.add_argument("--limit", type=int, help="only the first N problems of the list")
    ap.add_argument("--seeds", default=SEEDS, help="seeds per problem (default 1-12)")
    ap.add_argument("--cap", type=int, default=CAP, help="codelet cap (default 6000)")
    ap.add_argument("--stage", choices=("search", "record", "compare", "all"), default="all")
    ap.add_argument("--jobs", type=int, default=3, help="Docker containers at once (default 3)")
    ap.add_argument("--out", default=str(wrap.DEFAULT_OUT / "snag-sweep"))
    args = ap.parse_args(argv)

    out = Path(args.out)
    problems = wrap.read_problem_list(DATA / "snag_sweep_with_snags.txt" if args.only_known else args.problems)
    if args.limit:
        problems = problems[: args.limit]
    seeds = wrap.parse_seeds(args.seeds)

    stage = args.stage
    if stage in ("search", "all"):
        with concurrent.futures.ThreadPoolExecutor(args.jobs) as pool:
            list(pool.map(lambda p: search_problem(p, seeds, args.cap, out), problems))
    with_snags = [p for p in problems if (out / "search" / f"{slug(p)}.tsv").exists()
                  and has_snag(out / "search" / f"{slug(p)}.tsv")]
    print(f"{len(with_snags)} of {len(problems)} problems hit a snag within seeds {args.seeds}, cap {args.cap}")
    if stage in ("record", "all"):
        for p in with_snags:  # record.py parallelises over seeds itself
            record_traces(p, args.seeds, args.cap, out, args.jobs)
    if stage not in ("compare", "all"):
        return 0

    total = collections.Counter()
    kinds: collections.Counter = collections.Counter()
    for p in with_snags:
        lines = (out / "search" / f"{slug(p)}.tsv").read_text(encoding="utf-8").splitlines()
        t = compare_snags.compare_problem(slug(p), compare_snags.parse_metacat(lines),
                                          (out / "traces",) + compare_snags.TRACE_ROOTS)
        kinds.update(t.pop("kinds", {}))
        total.update(t)
        print(f"{slug(p)}: snags {t.get('snags_matched', 0)}/{t.get('snags', 0)}, "
              f"comments {t.get('comments_matched', 0)}/{t.get('comments', 0)}, "
              f"{t.get('desynced_runs', 0)} desynced, {t.get('no_trace', 0)} without a trace", flush=True)
    print(f"TOTAL {total['runs']} runs, snags {total['snags_matched']}/{total['snags']}, "
          f"comments {total['comments_matched']}/{total['comments']}, "
          f"{total['desynced_runs']} desynced runs; kinds {dict(kinds)}")
    return 0 if total["snags_matched"] == total["snags"] and total["comments_matched"] == total["comments"] else 1


if __name__ == "__main__":
    sys.exit(main())
