#!/usr/bin/env python3
"""Compare Metacat's slippage logs and supporting structure with Petacat's replay.

Every answer and snag event Metacat 1.2 records is read for the slippage log its rule
translation made (``answers.ss:1198``), its supporting vertical bridges, the rules'
reference objects and (answers) the supporting groups, by
``tests/lockstep/metacat/record_translation.py``.  The same run's recorded decisions are
replayed in Petacat (the lockstep harness, ``ReplayRNG``) and the ``translation`` block
of each answer and snag picture is compared with it, field by field.

    scripts/compare_translation_log.py abc-abd-xyz 1-10                 # discovery runs
    scripts/compare_translation_log.py abc-abd-xyz-wyz 1-5 --justify    # justify mode
    scripts/compare_translation_log.py --fixture                        # regenerate the fixture

Needs Docker and the ``metacat:1.2`` image, and the lockstep traces of the problem.
``--traces`` names another corpus root (default ``tests/lockstep/traces``); ``--out DIR``
keeps the Metacat recording (default: a temporary directory).  Exit status 1 if any
field differs.

``--fixture`` rewrites ``tests/lockstep/translation_log_metacat.tsv``, the record
``tests/lockstep/test_translation_log.py`` checks, for the runs in ``FIXTURE_RUNS``
(traces in ``tests/lockstep/traces-translation/``).
"""

from __future__ import annotations

import argparse
import collections
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from server.engine.runner import EngineRunner  # noqa: E402
from tests.lockstep.run_trace import replay_trace  # noqa: E402

RECORDER = ROOT / "tests/lockstep/metacat/record_translation.py"
FIXTURE = ROOT / "tests/lockstep/translation_log_metacat.tsv"
FIXTURE_TRACES = ROOT / "tests/lockstep/traces-translation"
#: ``(slug, seed)``: the smallest runs with a coattail slippage (``a-b-z`` 6 and 22, and a
#: justify-mode answer), directly applied slippages, a snag with an applied slippage, and
#: an answer whose supporting groups are nested.  A slug of four parts is justify mode.
FIXTURE_RUNS = [
    ("a-b-z", 22), ("a-b-z", 6), ("a-b-z", 4), ("xqc-xqd-mrrjjj", 1),
    ("abc-cba-mrrjjj", 29), ("rst-rsu-xyz-wyz", 1),
]
TYPES = {"answer": "answer_found", "snag": "snag"}


def parse_seeds(text: str) -> list[int]:
    lo, _, hi = text.partition("-")
    return list(range(int(lo), int(hi or lo) + 1))


def metacat_events(slug: str, seeds: str, justify: bool) -> dict:
    """``{seed: [(codelet, kind, payload)]}`` and ``{seed: end codelet}`` from Metacat 1.2."""
    parts = slug.split("-")
    seeds = seeds if "-" in seeds else f"{seeds}-{seeds}"
    cmd = [sys.executable, str(RECORDER), *parts[:3], seeds]
    if justify:
        cmd += ["--answer", parts[3]]
    out = subprocess.run(cmd, capture_output=True, text=True, check=True).stdout
    events: dict = collections.defaultdict(list)
    for line in out.splitlines():
        f = line.split("\t")
        if f[0] == "TR":
            events[f[1]].append((int(f[2]), f[3], json.loads(f[4])))
    return events


def petacat_events(trace: Path) -> tuple[int, list]:
    """Replay ``trace``: ``(end codelet, [(codelet, kind, translation block)])``."""
    current: dict = {}
    original = EngineRunner.init_mcat

    def capture(self, *args, **kwargs):
        current["runner"] = self
        return original(self, *args, **kwargs)

    EngineRunner.init_mcat = capture
    try:
        with tempfile.TemporaryDirectory() as out:
            _, outcome, _ = replay_trace(trace, out)
    finally:
        EngineRunner.init_mcat = original
    events = []
    for e in current["runner"].ctx.trace.events:
        if e.event_type in TYPES.values():
            block = e.picture["translation"]
            block["slippage_log"].pop("rule_type")
            kind = "answer" if e.event_type == "answer_found" else "snag"
            events.append((e.codelet_count, kind, block))
    return outcome.c, events


def write_fixture() -> None:
    header = [
        "# Metacat 1.2's slippage logs and supporting structures for every answer and snag in six runs, recorded: problem slug, seed, codelet count, event type, then a JSON object.",
        "# Regenerate: scripts/compare_translation_log.py --fixture   (records with tests/lockstep/metacat/record_translation.py; see tests/lockstep/test_translation_log.py)",
        "# Objects are 'string:left-right'; bridges 'orientation:l1-r1:l2-r2'; concept mappings {type, from, label, to} by short name.",
    ]
    rows = []
    for slug, seed in FIXTURE_RUNS:
        justify = len(slug.split("-")) == 4
        trace = FIXTURE_TRACES / slug / f"{seed}.metacat.jsonl.gz"
        end, _ = petacat_events(trace)
        for codelet, kind, payload in metacat_events(slug, str(seed), justify).get(str(seed), []):
            if codelet <= end:
                rows.append("\t".join([slug, str(seed), str(codelet), kind, json.dumps(payload, separators=(",", ":"))]))
    FIXTURE.write_text("\n".join(header + rows) + "\n")
    print(f"wrote {len(rows)} events to {FIXTURE.relative_to(ROOT)}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("slug", nargs="?", help="problem (i-m-t), or i-m-t-answer with --justify")
    ap.add_argument("seeds", nargs="?", help="seed or LO-HI")
    ap.add_argument("--justify", action="store_true")
    ap.add_argument("--fixture", action="store_true", help="regenerate the committed fixture")
    ap.add_argument("--traces", default=str(ROOT / "tests/lockstep/traces"))
    ap.add_argument("--out", help="keep the Metacat recording in this directory")
    args = ap.parse_args()
    if args.fixture:
        write_fixture()
        return 0
    if not (args.slug and args.seeds):
        ap.error("slug and seeds are required (or --fixture)")

    base = Path(args.traces) / ("justify" if args.justify else "")
    mc = metacat_events(args.slug, args.seeds, args.justify)
    if args.out:
        Path(args.out).mkdir(parents=True, exist_ok=True)
        (Path(args.out) / f"{args.slug}.{args.seeds}.json").write_text(json.dumps(mc))
    runs = identical = events = matched = 0
    for seed in parse_seeds(args.seeds):
        trace = base / args.slug / f"{seed}.metacat.jsonl.gz"
        if not trace.exists():
            continue
        end, got = petacat_events(trace)
        want = [x for x in mc.get(str(seed), []) if x[0] <= end]
        runs += 1
        events += len(want)
        matched += sum(1 for a, b in zip(want, got) if a == b)
        if want == got:
            identical += 1
        else:
            print(f"DIFF {args.slug} {seed}")
            for a, b in zip(want, got):
                if a != b:
                    for k in sorted(set(a[2]) | set(b[2])):
                        if a[2].get(k) != b[2].get(k):
                            print(f"  {a[0]} {a[1]} {k}\n    Metacat: {a[2].get(k)}\n    Petacat: {b[2].get(k)}")
                    break
    print(f"{args.slug}: {identical}/{runs} runs identical, {matched}/{events} answers and snags identical")
    return 0 if identical == runs else 1


if __name__ == "__main__":
    sys.exit(main())
