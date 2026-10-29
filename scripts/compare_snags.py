#!/usr/bin/env python3
"""Compare Metacat's snag explanations and snag commentary with Petacat's replay of the run.

For every snag Metacat 1.2 hits, ``tests/lockstep/metacat/record_snags.py`` logs the failure
kind, the snag event's ``get-explanation`` and the two comment lines ``process-snag`` adds.
Petacat replays the recorded Metacat trace of the same run (the lockstep harness,
``ReplayRNG``), which reproduces the same snags at the same codelets, and what its trace
events and commentary hold must equal the log character for character.

    scripts/compare_snags.py abc-abd-xyz 1-10                 # corpus traces, cap 100000
    scripts/compare_snags.py a-b-xyz 1-12 --cap 6000 --traces DIR
    scripts/compare_snags.py --regenerate-fixture --out DIR   # rebuild snag_explanations_metacat.tsv

Needs Docker, the ``metacat:1.2`` image and the lockstep traces of the problem (record them
with ``tests/lockstep/metacat/record.py``; ``--traces`` is searched after
``tests/lockstep/traces-snags`` and ``tests/lockstep/traces``).  A replay that desynchronises
stops short of the record; only the snags before it are compared and the run is reported as
``desynced``.  Exit status 1 if any compared snag differs.

``--regenerate-fixture`` records, in the committed fixture's cap (6000), every (problem, seed)
the committed ``tests/lockstep/snag_explanations_metacat.tsv`` holds, writes the rebuilt file to
``--out`` (default ``tests/lockstep/out``) and reports whether it equals the committed one
apart from the ``#`` header lines.  It never overwrites the committed file.  About one minute.
"""

from __future__ import annotations

import argparse
import collections
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests" / "lockstep" / "metacat"))

import record_snags  # noqa: E402
import wrap  # noqa: E402

FIXTURE = ROOT / "tests" / "lockstep" / "snag_explanations_metacat.tsv"
FIXTURE_CAP = 6000
TRACE_ROOTS = (ROOT / "tests" / "lockstep" / "traces-snags", ROOT / "tests" / "lockstep" / "traces")
FIXTURE_HEADER = (
    "# Metacat 1.2's snags, recorded: problem slug, seed, codelet count, failure kind, "
    "get-explanation, the Eliza comment, the technical comment.\n"
    "# Logged by wrapping make-snag-event and the comment window in the reference container "
    "(cap 6000 codelets); see tests/lockstep/test_snag_explanations.py.\n"
    "# Regenerate: python3 scripts/compare_snags.py --regenerate-fixture --out DIR "
    "(recorder: tests/lockstep/metacat/record_snags.py --cap 6000)\n"
)


def parse_metacat(lines) -> dict:
    """``record_snags.py`` output -> ``{seed: {"snags": [(c, kind, explanation)],
    "comments": [(c, eliza, technical)], "end": (c, outcome) | None}}``, runs in order."""
    runs: dict = collections.OrderedDict()
    for line in lines:
        f = line.rstrip("\n").split("\t")
        run = runs.setdefault(f[1], {"snags": [], "comments": [], "end": None}) if len(f) > 1 else None
        if f[0] == "SNAG":
            run["snags"].append((int(f[2]), f[3], f[4]))
        elif f[0] == "CMT":
            run["comments"].append((int(f[2]), f[3], f[4]))
        elif f[0] == "END":
            run["end"] = (int(f[2]), f[3])
    return runs


def fixture_rows(slug: str, runs: dict) -> list[tuple]:
    """Join each snag with the comment added at its codelet count: the committed fixture's
    ``(slug, seed, codelet, kind, explanation, eliza, technical)`` rows."""
    rows = []
    for seed, run in runs.items():
        by_count = {c: (e, t) for c, e, t in run["comments"]}
        for c, kind, explanation in run["snags"]:
            eliza, technical = by_count[c]
            rows.append((slug, seed, str(c), kind, explanation, eliza, technical))
    return rows


def read_fixture(path: Path = FIXTURE) -> list[tuple]:
    """The data rows of a fixture file (``#`` lines and blanks skipped)."""
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.startswith("#"):
            rows.append(tuple(line.split("\t")))
    return rows


def write_fixture(path: Path, rows: list[tuple]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as out:
        out.write(FIXTURE_HEADER)
        for r in rows:
            out.write("\t".join(r) + "\n")


def find_trace(slug: str, seed, roots=TRACE_ROOTS) -> Path | None:
    for root in roots:
        path = Path(root) / slug / f"{seed}.metacat.jsonl.gz"
        if path.exists():
            return path
    return None


def petacat_snags(trace: Path):
    """Replay ``trace``; return ``(snags, comments, outcome)`` in the shapes of
    ``parse_metacat`` (kind upper-cased as Metacat's symbols are)."""
    from server.engine.runner import EngineRunner
    from server.engine.trace import SNAG
    from tests.lockstep.run_trace import replay_trace

    holder: dict = {}
    original = EngineRunner.init_mcat

    def capture(self, *args, **kwargs):
        holder["runner"] = self
        return original(self, *args, **kwargs)

    EngineRunner.init_mcat = capture
    try:
        with tempfile.TemporaryDirectory() as out:
            _, outcome, _ = replay_trace(trace, out)
    finally:
        EngineRunner.init_mcat = original
    ctx = holder["runner"].ctx
    snags = [(e.codelet_count, e.snag_type.upper(), e.explanation)
             for e in ctx.trace.events if e.event_type == SNAG]
    comments = [(p.codelet_count, p.eliza_text, p.technical_text)
                for p in ctx.commentary.get_paragraphs() if p.event_type == "snag"]
    return snags, comments, outcome


def compare_run(expected: dict, snags: list, comments: list, stop: int | None = None) -> dict:
    """Compare one run.  ``stop`` is the codelet count at which the replay stopped
    desynchronised (None when it ran to the end): only Metacat's snags before it count."""
    want_s, want_c = expected["snags"], expected["comments"]
    if stop is not None:
        want_s = [s for s in want_s if s[0] < stop]
        want_c = [c for c in want_c if c[0] < stop]
    first = next((i for i, (a, b) in enumerate(zip(want_s, snags)) if a != b),
                 None if len(want_s) == len(snags) else min(len(want_s), len(snags)))
    cfirst = next((i for i, (a, b) in enumerate(zip(want_c, comments)) if a != b),
                  None if len(want_c) == len(comments) else min(len(want_c), len(comments)))
    return {
        "snags": len(want_s),
        "snags_matched": sum(1 for a, b in zip(want_s, snags) if a == b),
        "comments": len(want_c),
        "comments_matched": sum(1 for a, b in zip(want_c, comments) if a == b),
        "identical": first is None and cfirst is None,
        "first": first, "comment_first": cfirst,
        "desynced": stop is not None,
        "want_snag": want_s[first] if first is not None and first < len(want_s) else None,
        "got_snag": snags[first] if first is not None and first < len(snags) else None,
        "want_comment": want_c[cfirst] if cfirst is not None and cfirst < len(want_c) else None,
        "got_comment": comments[cfirst] if cfirst is not None and cfirst < len(comments) else None,
    }


def compare_problem(slug: str, runs: dict, roots=TRACE_ROOTS, say=print) -> dict:
    """Replay every run of ``runs`` (``parse_metacat`` output) that has a trace and compare."""
    total = collections.Counter()
    kinds = collections.Counter()
    for seed, expected in runs.items():
        trace = find_trace(slug, seed, roots)
        if trace is None:
            total["no_trace"] += 1
            continue
        snags, comments, outcome = petacat_snags(trace)
        stop = outcome.c if outcome.reason == "fatal" else None
        r = compare_run(expected, snags, comments, stop)
        total["runs"] += 1
        total["identical_runs"] += r["identical"]
        total["desynced_runs"] += r["desynced"]
        for k in ("snags", "snags_matched", "comments", "comments_matched"):
            total[k] += r[k]
        kinds.update(k for _, k, _ in (expected["snags"] if stop is None
                                         else [s for s in expected["snags"] if s[0] < stop]))
        if not r["identical"]:
            say(f"DIFF {slug} seed {seed}" + (f" (replay desynced at codelet {stop})" if r["desynced"] else ""))
            if r["first"] is not None:
                say("  Metacat snag:", r["want_snag"])
                say("  Petacat snag:", r["got_snag"])
            if r["comment_first"] is not None:
                say("  Metacat comment:", r["want_comment"])
                say("  Petacat comment:", r["got_comment"])
    total["kinds"] = dict(kinds)
    return dict(total)


def regenerate(out_dir: Path, fixture: Path = FIXTURE, cap: int = FIXTURE_CAP) -> int:
    """Record the fixture's runs again; write ``out_dir/<fixture name>``; report the diff."""
    committed = read_fixture(fixture)
    order: list[tuple[str, str]] = []
    for r in committed:
        if (r[0], r[1]) not in order:
            order.append((r[0], r[1]))
    by_slug: dict = collections.OrderedDict()
    for slug, seed in order:
        by_slug.setdefault(slug, []).append(int(seed))
    runs_by_key: dict = {}
    for slug, seeds in by_slug.items():
        out = record_snags.record(wrap.slug_problem(slug), seeds, cap)
        for seed, run in parse_metacat(out).items():
            runs_by_key[(slug, seed)] = run
    rows = []
    for slug, seed in order:
        rows += fixture_rows(slug, {seed: runs_by_key[(slug, seed)]})
    target = out_dir / fixture.name
    write_fixture(target, rows)
    same = rows == committed
    print(f"{len(rows)} snag rows over {len(order)} runs written to {target}")
    print("identical to the committed fixture apart from # lines" if same else
          f"DIFFERS from the committed fixture ({len(committed)} rows there)")
    if not same:
        for a, b in zip(rows, committed):
            if a != b:
                print("  first difference:\n   new      ", a, "\n   committed", b)
                break
    return 0 if same else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("slug", nargs="?", help="problem slug i-m-t")
    ap.add_argument("seeds", nargs="?", help="seed list such as 1-12 or 1,5")
    ap.add_argument("--cap", type=int, default=100000, help="Metacat codelet cap (default 100000)")
    ap.add_argument("--traces", help="extra trace corpus root searched first (<root>/<slug>/<seed>.metacat.jsonl.gz)")
    ap.add_argument("--metacat-lines", help="a saved record_snags.py output to compare instead of recording")
    ap.add_argument("--regenerate-fixture", action="store_true")
    ap.add_argument("--out", default=str(wrap.DEFAULT_OUT), help="output directory (default tests/lockstep/out)")
    args = ap.parse_args(argv)

    if args.regenerate_fixture:
        return regenerate(Path(args.out))
    if not args.slug or not args.seeds:
        ap.error("slug and seeds are required unless --regenerate-fixture")
    roots = ((Path(args.traces),) if args.traces else ()) + TRACE_ROOTS
    if args.metacat_lines:
        lines = Path(args.metacat_lines).read_text(encoding="utf-8").splitlines()
    else:
        lines = record_snags.record(wrap.slug_problem(args.slug), wrap.parse_seeds(args.seeds), args.cap)
    runs = parse_metacat(lines)
    t = compare_problem(args.slug, runs, roots)
    print(f"{args.slug}: {t.get('runs', 0)} runs compared ({t.get('no_trace', 0)} without a trace, "
          f"{t.get('desynced_runs', 0)} desynced), snags {t.get('snags_matched', 0)}/{t.get('snags', 0)}, "
          f"comments {t.get('comments_matched', 0)}/{t.get('comments', 0)}, kinds {t.get('kinds', {})}")
    return 0 if t.get("snags_matched", 0) == t.get("snags", 0) and t.get("comments_matched", 0) == t.get("comments", 0) else 1


if __name__ == "__main__":
    sys.exit(main())
