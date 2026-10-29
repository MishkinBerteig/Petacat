#!/usr/bin/env python3
"""Compare Metacat's commentary with Petacat's replay of the same run, line for line.

Every paragraph the comment window receives (both voices, with the codelet count it was
added at) is logged from Metacat 1.2 by ``tests/lockstep/metacat/record_comments.py`` and
compared with the paragraphs Petacat's ``CommentaryLog`` holds after replaying the
recorded Metacat trace (the lockstep harness, ``ReplayRNG``).  The opening "Beginning
run" paragraph is left out on both sides.

    scripts/compare_commentary.py abc-abd-xyz 1-10                  # discovery runs
    scripts/compare_commentary.py abc-abd-xyz-wyz 1-5 --justify     # justify mode
    scripts/compare_commentary.py abc-abd-xyz 1-3 --episode         # 8-run episodes

Needs Docker and the ``metacat:1.2`` image, and the lockstep traces of the problem
(``tests/lockstep/metacat/record.py`` records them).  ``--traces`` names another corpus
root (default ``tests/lockstep/traces``).  Exit status 1 if any run differs.
"""

from __future__ import annotations

import argparse
import collections
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


def metacat_commentary(slug: str, seeds: str, justify: bool, episode: bool) -> dict:
    """``{key: [(codelet_count, eliza, technical), ...]}`` from Metacat 1.2."""
    parts = slug.split("-")
    problem, answer = parts[:3], (parts[3] if justify else None)
    cmd = [sys.executable, str(ROOT / "tests/lockstep/metacat/record_comments.py"), *problem, seeds]
    if answer:
        cmd += ["--answer", answer]
    if episode:
        cmd += ["--episode", str(RUNS_PER_EPISODE)]
    out = subprocess.run(cmd, capture_output=True, text=True, check=True).stdout
    runs: dict = collections.OrderedDict()
    for line in out.splitlines():
        f = line.split("\t")
        if f[0] == "CMT":
            runs.setdefault(f[1], []).append(tuple(f[2:5]))
        elif f[0] == "END":
            runs.setdefault(f[1], [])
    return runs


def petacat_commentary(trace: Path, memory: EpisodicMemory | None, name: str | None) -> list:
    """Replay ``trace`` in Petacat and return its commentary in the same shape."""
    current: dict = {}
    original = EngineRunner.init_mcat

    def capture(self, *args, **kwargs):
        current["runner"] = self
        return original(self, *args, **kwargs)

    EngineRunner.init_mcat = capture
    try:
        with tempfile.TemporaryDirectory() as out:
            replay_trace(trace, out, memory=memory, name=name)
    finally:
        EngineRunner.init_mcat = original
    return [
        (str(p.codelet_count), p.eliza_text, p.technical_text)
        for p in current["runner"].ctx.commentary.get_paragraphs()
        if p.event_type != "new_problem"
    ]


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
    mc = metacat_commentary(args.slug, args.seeds, args.justify, args.episode)
    pc: dict = {}
    for seed in parse_seeds(args.seeds):
        if args.episode:
            memory = EpisodicMemory()
            first = base / args.slug / f"{seed}.r1.metacat.jsonl.gz"
            for meta in episode_runs(first):
                stem = ".".join(meta.name.split(".")[:2])
                pc[stem] = petacat_commentary(meta, memory, stem)
        else:
            trace = base / args.slug / f"{seed}.metacat.jsonl.gz"
            if trace.exists():
                pc[str(seed)] = petacat_commentary(trace, None, None)

    runs = identical = lines = matched = 0
    for key, expected in mc.items():
        if key not in pc:
            continue
        runs += 1
        got = pc[key]
        lines += len(expected)
        matched += sum(1 for a, b in zip(expected, got) if a == b)
        if expected == got:
            identical += 1
        else:
            first = next(
                (i for i, (a, b) in enumerate(zip(expected, got)) if a != b),
                min(len(expected), len(got)),
            )
            print(f"DIFF {args.slug} {key} line {first}")
            print("  Metacat:", expected[first] if first < len(expected) else None)
            print("  Petacat:", got[first] if first < len(got) else None)
    print(f"{args.slug}: {identical}/{runs} runs identical, {matched}/{lines} lines identical")
    return 0 if identical == runs else 1


if __name__ == "__main__":
    sys.exit(main())
