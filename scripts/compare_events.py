#!/usr/bin/env python3
"""Compare the Temporal Trace event names and headers Metacat reports with Petacat's.

Reproduces the check behind ``tests/lockstep/event_names_metacat.tsv`` (3,755 of 3,757
events matched when first run; the one swap found then was fixed).  Metacat 1.2 is run by
``tests/lockstep/metacat/record_events.py``, which asks every event of ``*trace*`` for its
print-name and header.  Petacat replays the recorded lockstep trace of the same run
(``ReplayRNG``), which reproduces the same events at the same codelets, and each event's
type, codelet, print-name (``print_name``) and header (``picture["header"]``) must be equal.
Metacat runs a few codelets past an answer before its driver's suspend lands; the
comparison keeps the Metacat events up to the codelet Petacat's replay ended at.

    python3 scripts/compare_events.py                      # the eight runs of the fixture
    python3 scripts/compare_events.py --table OUT.tsv      # ... and write the fixture format
    python3 scripts/compare_events.py --corpus             # whole corpus: discovery seeds
                                                           # 1-10, justify seeds 1-5
    python3 scripts/compare_events.py --corpus --pick 3500 30000 --table OUT.tsv

``--runs FILE`` (default ``tests/lockstep/event_names_runs.txt``) lists ``<kind> <slug>
<seed>`` runs (kind ``main`` or ``justify``).  ``--corpus`` takes every trace directory under
``--traces`` (default ``tests/lockstep/traces``).  ``--pick LIMIT...`` chooses, for each codelet
limit, the smallest fully matching runs that between them hold every event type and every kind
of header (greedy cover) and writes them to ``--table``: how the fixture's eight runs were
chosen.  Needs Docker, the ``metacat:1.2`` image and the lockstep traces.  The default takes
about 1 minute; ``--corpus`` about 13 minutes with ``--jobs 2``.  Exit status 1 if any run differs.
"""

from __future__ import annotations

import argparse
import collections
import concurrent.futures
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests" / "lockstep" / "metacat"))

import record_events as recorder  # noqa: E402

DEFAULT_RUNS = ROOT / "tests" / "lockstep" / "event_names_runs.txt"
DEFAULT_TRACES = ROOT / "tests" / "lockstep" / "traces"

#: Metacat's event types -> Petacat's.
TYPES = {
    "concept-activation": "concept_activation",
    "group": "group_built",
    "concept-mapping": "concept_mapping_built",
    "rule": "rule_built",
    "answer": "answer_found",
    "snag": "snag",
    "clamp": "clamp_start",
}

TABLE_HEADER = (
    "# Metacat 1.2's Temporal Trace events: print-name (trace.ss) and the header display-workspace draws.\n"
    "# Logged by running Metacat headless (metacat:1.2) and, after each run, asking every event of *trace* for\n"
    "# 'print-name and for the header its 'display-workspace sends to draw-event-header.\n"
    "# Regenerate: python3 scripts/compare_events.py --table <path>   (runs: tests/lockstep/event_names_runs.txt)\n"
    "# Columns: kind (main = traces/, justify = traces/justify/), slug, seed, event number, event type, codelet, print-name, header\n"
)


# --- pure logic (tests/lockstep/test_compare_events.py) ------------------------------


def parse_runs_file(text):
    """``<kind> <slug> <seed>`` lines -> ``[(kind, slug, seed)]`` (comments skipped)."""
    runs = []
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            kind, slug, seed = line.split()
            if kind not in ("main", "justify"):
                raise ValueError(f"unknown kind {kind!r}")
            runs.append((kind, slug, int(seed)))
    return runs


def parse_events(lines):
    """EV/END lines -> ``{seed: [(number, type, codelet, print-name, header)]}``.

    Metacat's event type is mapped to Petacat's; a type with no mapping is kept as is."""
    runs: dict = collections.OrderedDict()
    for line in lines:
        f = line.rstrip("\n").split("\t")
        if f[0] == "EV":
            runs.setdefault(int(f[1]), []).append(
                (int(f[2]), TYPES.get(f[3], f[3]), int(f[4]), f[6], f[7]))
        elif f[0] == "END":
            runs.setdefault(int(f[1]), [])
    return runs


def comparable(events):
    """The part of an event the comparison checks (not its number)."""
    return [e[1:] for e in events]


def truncate(events, reached):
    """The events Metacat logged up to codelet ``reached``."""
    return [e for e in events if e[2] <= reached]


def first_difference(metacat, petacat):
    """Index of the first event that differs (or of the shorter list's end); None if equal."""
    for i, (a, b) in enumerate(zip(metacat, petacat)):
        if a != b:
            return i
    return None if len(metacat) == len(petacat) else min(len(metacat), len(petacat))


def features(events):
    """What a run shows: header kinds, event types, concept-mapping kinds, group shapes."""
    feats = set()
    for _n, etype, _c, name, header in events:
        header = re.sub(r"Made .* slippage", "Made X slippage", header)
        header = re.sub(r"Activation of .* concept", "Activation of X concept", header)
        feats.add(header)
        feats.add(etype)
        if etype == "concept_mapping_built":
            feats.add("cm:" + name[0])
        if etype == "group_built":
            feats.add("grp:" + re.sub(r"[a-z0-9A-Z-]+", "x", name))
    return feats


def pick_cover(candidates, limits):
    """Greedy cover.  ``candidates``: ``[(key, limit_codelets, events)]``; for each limit the
    runs with ``limit_codelets <= limit`` are searched, most uncovered features first, smaller
    runs on ties.  Returns the chosen candidates in choice order."""
    cands = [(k, lim, ev, features(ev)) for k, lim, ev in candidates]
    chosen: list = []
    for limit in limits:
        pool = [c for c in cands if c[1] <= limit]
        if not pool:
            continue
        everything = set().union(*[c[3] for c in pool])
        covered: set = set()
        while covered != everything:
            best = max(pool, key=lambda c: (len(c[3] - covered), -c[1]))
            if not best[3] - covered:
                break
            if best not in chosen:
                chosen.append(best)
            covered |= best[3]
    return [(k, lim, ev) for k, lim, ev, _f in chosen]


def format_table(rows):
    """``rows``: ``[(kind, slug, seed, [events])]`` -> the fixture text."""
    out = [TABLE_HEADER]
    for kind, slug, seed, events in rows:
        for n, etype, codelet, name, header in events:
            out.append("\t".join([kind, slug, str(seed), str(n), etype, str(codelet), name, header]) + "\n")
    return "".join(out)


# --- the two sides --------------------------------------------------------------------


def trace_path(traces, kind, slug, seed):
    base = Path(traces) / ("justify" if kind == "justify" else "") / slug
    return base / f"{seed}.metacat.jsonl.gz"


def petacat_events(trace):
    """Replay ``trace`` in Petacat: ``(codelet count reached, [(number, type, codelet, name, header)])``."""
    from server.engine.runner import EngineRunner
    from tests.lockstep.run_trace import replay_trace

    holder: dict = {}
    original = EngineRunner.init_mcat

    def capture(self, *a, **k):
        holder["r"] = self
        return original(self, *a, **k)

    EngineRunner.init_mcat = capture
    try:
        with tempfile.TemporaryDirectory() as out:
            _path, outcome, _rng = replay_trace(trace, out)
    finally:
        EngineRunner.init_mcat = original
    events = [
        (e.event_number, e.event_type, e.codelet_count, e.print_name,
         (e.picture or {}).get("header", "NOPICTURE"))
        for e in holder["r"].ctx.trace.events
    ]
    return outcome.c, events


def _petacat_job(path):
    return petacat_events(path)


def corpus_entries(traces, discovery_seeds, justify_seeds):
    """Every (kind, slug, seeds) of the trace corpus."""
    traces = Path(traces)
    entries = []
    for d in sorted(p.name for p in traces.iterdir() if p.is_dir()):
        if d in ("episodes", "episodes-justify", "justify"):
            continue
        entries.append(("main", d, discovery_seeds))
    if (traces / "justify").is_dir():
        for d in sorted(p.name for p in (traces / "justify").iterdir() if p.is_dir()):
            entries.append(("justify", d, justify_seeds))
    return entries


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--runs", default=str(DEFAULT_RUNS), help="file of '<kind> <slug> <seed>' lines")
    ap.add_argument("--corpus", action="store_true", help="the whole trace corpus instead of --runs")
    ap.add_argument("--traces", default=str(DEFAULT_TRACES))
    ap.add_argument("--discovery-seeds", default="1-10")
    ap.add_argument("--justify-seeds", default="1-5")
    ap.add_argument("--pick", type=int, nargs="+", metavar="LIMIT",
                    help="choose a covering set of runs per codelet limit (needs --table)")
    ap.add_argument("--table", help="write the fixture-format table here")
    ap.add_argument("--jobs", type=int, default=2, help="containers / processes at once (default 2)")
    args = ap.parse_args()
    if args.pick and not args.table:
        ap.error("--pick needs --table")

    wrap = recorder.wrap
    if args.corpus:
        entries = corpus_entries(args.traces, wrap.parse_seeds(args.discovery_seeds),
                                 wrap.parse_seeds(args.justify_seeds))
    else:
        grouped: dict = collections.OrderedDict()
        for kind, slug, seed in parse_runs_file(Path(args.runs).read_text()):
            grouped.setdefault((kind, slug), []).append(seed)
        entries = [(k, s, seeds) for (k, s), seeds in grouped.items()]

    def metacat(entry):
        kind, slug, seeds = entry
        parts = slug.split("-")
        answer = parts[3] if kind == "justify" else None
        return parse_events(recorder.record(parts[:3], seeds, answer))

    with concurrent.futures.ThreadPoolExecutor(args.jobs) as pool:
        mc_runs = list(pool.map(metacat, entries))

    jobs = [(kind, slug, seed) for kind, slug, seeds in entries for seed in seeds]
    paths = [trace_path(args.traces, *j) for j in jobs]
    present = [p for p in paths if p.exists()]
    with concurrent.futures.ProcessPoolExecutor(args.jobs) as pool:
        replayed = dict(zip(present, pool.map(_petacat_job, present)))

    mc_by_run = {}
    for (kind, slug, seeds), runs in zip(entries, mc_runs):
        for seed in seeds:
            mc_by_run[(kind, slug, seed)] = runs.get(seed, [])

    runs = identical = n_events = n_ok = 0
    chosen_rows, candidates = [], []
    for job, path in zip(jobs, paths):
        if path not in replayed:
            print(f"SKIP {job}: no trace {path}")
            continue
        reached, pc = replayed[path]
        mc = truncate(mc_by_run[job], reached)
        runs += 1
        n_events += len(mc)
        n_ok += sum(1 for a, b in zip(comparable(mc), comparable(pc)) if a == b)
        diff = first_difference(comparable(mc), comparable(pc))
        if diff is None:
            identical += 1
            candidates.append((job, reached, mc))
        else:
            print(f"DIFF {' '.join(map(str, job))} event {diff}")
            print("  Metacat:", mc[diff] if diff < len(mc) else None)
            print("  Petacat:", pc[diff] if diff < len(pc) else None)
    print(f"{runs} runs: {identical} identical, {n_ok}/{n_events} events identical "
          f"(type, codelet, print-name, header)")

    if args.table:
        if args.pick:
            picked = pick_cover(candidates, args.pick)
            chosen_rows = [(k[0], k[1], k[2], ev) for k, _lim, ev in picked]
            print("picked:", [(k[0], k[1], k[2], lim) for k, lim, _ev in picked])
        else:
            chosen_rows = [(j[0], j[1], j[2], ev) for j, _lim, ev in candidates]
        Path(args.table).parent.mkdir(parents=True, exist_ok=True)
        Path(args.table).write_text(format_table(chosen_rows))
        print(f"{args.table}: {sum(len(r[3]) for r in chosen_rows)} events in {len(chosen_rows)} runs")
    return 0 if identical == runs else 1


if __name__ == "__main__":
    sys.exit(main())
