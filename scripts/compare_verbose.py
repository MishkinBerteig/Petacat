#!/usr/bin/env python3
"""Compare Metacat's Verbose-mode console output with Petacat's narration of the same run.

``tests/lockstep/metacat/record_verbose.py`` runs Metacat 1.2 with ``%verbose%`` on and logs
everything it prints: the dashed line and ``In <type> codelet...`` of every codelet and every
``say``, ``vprintf`` and ``vprint``.  The recorded trace of the same run is replayed in Petacat
(the lockstep harness, ``ReplayRNG``) with Verbose mode on, which reproduces the run, and the
lines of Petacat's ``VerboseLog`` are compared with Metacat's, line for line.

    scripts/compare_verbose.py abc-abd-xyz 1-5                  # discovery runs
    scripts/compare_verbose.py abc-abd-xyz-wyz 1-3 --justify    # justify mode
    scripts/compare_verbose.py abc-abd-xyz 1 --episode          # 8-run episodes

Needs Docker and the ``metacat:1.2`` image, and the lockstep traces of the problem
(``tests/lockstep/metacat/record.py`` records them).  ``--traces`` names another corpus root
(default ``tests/lockstep/traces``).  Prints, per slug, how many runs are identical and how
many of Metacat's lines Petacat also said (aligned, so one missing line does not lose the rest);
exit status 1 if any run differs.
"""

from __future__ import annotations

import argparse
import collections
import difflib
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from server.engine.memory import EpisodicMemory  # noqa: E402
from server.engine.runner import EngineRunner  # noqa: E402
from tests.lockstep.run_trace import episode_runs, replay_trace  # noqa: E402

RUNS_PER_EPISODE = 8


def parse_seeds(text: str) -> list[int]:
    lo, _, hi = text.partition("-")
    return list(range(int(lo), int(hi or lo) + 1))


def parse_record(text: str) -> dict:
    """``{key: [line, ...]}`` from ``record_verbose.py``'s output."""
    runs: dict = collections.OrderedDict()
    key = None
    for line in text.split("\n"):
        if line.startswith("@@RUN\t"):
            key = line.split("\t")[1]
            runs[key] = []
        elif line.startswith("@@END\t"):
            key = None
        elif key is not None:
            runs[key].append(line)
    return runs


def metacat_verbose(slug: str, seeds: str, justify: bool, episode: bool) -> dict:
    parts = slug.split("-")
    problem, answer = parts[:3], (parts[3] if justify else None)
    cmd = [sys.executable, str(ROOT / "tests/lockstep/metacat/record_verbose.py"), *problem, seeds]
    if answer:
        cmd += ["--answer", answer]
    if episode:
        cmd += ["--episode", str(RUNS_PER_EPISODE)]
    return parse_record(subprocess.run(cmd, capture_output=True, text=True, check=True).stdout)


def petacat_verbose(trace: Path, memory: EpisodicMemory | None, name: str | None) -> list[str]:
    """Replay ``trace`` in Petacat with Verbose mode on; the whole narration, unbounded."""
    current: dict = {}
    original = EngineRunner.init_mcat

    def capture(self, *args, **kwargs):
        current["runner"] = self
        self.verbose_mode = True
        result = original(self, *args, **kwargs)
        self.ctx.verbose_log._lines = collections.deque()
        return result

    EngineRunner.init_mcat = capture
    try:
        with tempfile.TemporaryDirectory() as out:
            replay_trace(trace, out, memory=memory, name=name)
    finally:
        EngineRunner.init_mcat = original
    return current["runner"].ctx.verbose_log.since(0)["lines"]


def matched_lines(expected: list[str], got: list[str]) -> int:
    """Lines of ``expected`` that ``got`` also has, in order (an aligned count)."""
    if expected == got:
        return len(expected)
    blocks = difflib.SequenceMatcher(None, expected, got, autojunk=False).get_matching_blocks()
    return sum(b.size for b in blocks)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("slug", help="problem (i-m-t), or i-m-t-answer with --justify")
    ap.add_argument("seeds", help="seed or LO-HI (episode seeds with --episode)")
    ap.add_argument("--justify", action="store_true")
    ap.add_argument("--episode", action="store_true")
    ap.add_argument("--traces", default=str(ROOT / "tests/lockstep/traces"))
    args = ap.parse_args()

    base = Path(args.traces)
    if args.justify:
        base = base / "justify"
    elif args.episode:
        base = base / "episodes"
    mc = metacat_verbose(args.slug, args.seeds, args.justify, args.episode)
    pc: dict = {}
    for seed in parse_seeds(args.seeds):
        if args.episode:
            memory = EpisodicMemory()
            first = base / args.slug / f"{seed}.r1.metacat.jsonl.gz"
            for meta in episode_runs(first):
                stem = ".".join(meta.name.split(".")[:2])
                pc[stem] = petacat_verbose(meta, memory, stem)
        else:
            trace = base / args.slug / f"{seed}.metacat.jsonl.gz"
            if trace.exists():
                pc[str(seed)] = petacat_verbose(trace, None, None)

    runs = identical = lines = matched = 0
    for key, expected in mc.items():
        if key not in pc:
            continue
        runs += 1
        got = pc[key]
        lines += len(expected)
        matched += matched_lines(expected, got)
        if expected == got:
            identical += 1
        else:
            first = next(
                (i for i, (a, b) in enumerate(zip(expected, got)) if a != b),
                min(len(expected), len(got)),
            )
            print(f"DIFF {args.slug} {key} line {first}")
            print("  Metacat:", repr(expected[first]) if first < len(expected) else None)
            print("  Petacat:", repr(got[first]) if first < len(got) else None)
    print(f"{args.slug}: {identical}/{runs} runs identical, {matched}/{lines} lines identical")
    return 0 if identical == runs else 1


if __name__ == "__main__":
    sys.exit(main())
