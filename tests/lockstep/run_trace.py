"""Command line: record Petacat's own trace, or replay against a Metacat trace.

    python -m tests.lockstep.run_trace record --problem abc abd xyz --seed 1 --cap 2000
    python -m tests.lockstep.run_trace replay --metacat tests/lockstep/traces/abc-abd-xyz/1.metacat.jsonl.gz

``record`` runs Petacat with ``TracingRNG`` and writes ``<seed>.petacat.jsonl.gz``.
``replay`` reads a Metacat trace, runs Petacat on the same problem, seed and cap with
every decision answered from the trace, and writes ``<seed>.petacat.jsonl.gz`` beside
it (or into ``--out``).  Both are faithful-mode runs (``faithful.py``).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from tests.lockstep.faithful import DEFAULT_CAP, Outcome, header_record, run_faithful
from tests.lockstep.replay_rng import MetacatTrace, ReplayRNG
from tests.lockstep.trace_io import TraceWriter
from tests.lockstep.tracing_rng import TracingRNG

TRACES = Path(__file__).resolve().parent / "traces"


def slug(problem: tuple[str, str, str]) -> str:
    return "-".join(problem)


def _finish(writer: TraceWriter, rng: Any, outcome: Outcome) -> None:
    if outcome.fatal is not None:
        writer.write({"t": "fatal", "class": outcome.fatal.fatal_class, "c": outcome.c,
                      "detail": outcome.fatal.detail})
    writer.write(outcome.record())
    writer.close()


def record_trace(problem: tuple[str, str, str], seed: int, cap: int = DEFAULT_CAP,
                 out_dir: str | Path | None = None) -> tuple[Path, Outcome]:
    """Petacat's own trace of one problem and seed (``TracingRNG``)."""
    out = Path(out_dir) if out_dir else TRACES / slug(problem)
    path = out / f"{seed}.petacat.jsonl.gz"
    writer = TraceWriter(path)
    writer.write(header_record(problem, seed, cap))
    rng = TracingRNG(seed, writer)
    outcome = run_faithful(problem, seed, cap, rng)
    _finish(writer, rng, outcome)
    return path, outcome


def replay_trace(metacat: str | Path, out_dir: str | Path | None = None,
                 cap: int | None = None, complemented_sites: tuple[str, ...] = (),
                 ) -> tuple[Path, Outcome, ReplayRNG]:
    """Replay ``metacat`` (a reference trace) in Petacat; returns the trace written."""
    trace = MetacatTrace(metacat)
    head = trace.header
    problem = tuple(head["problem"])
    seed = int(head["seed"])
    cap = int(cap if cap is not None else head.get("cap", DEFAULT_CAP))
    out = Path(out_dir) if out_dir else Path(metacat).parent
    path = out / f"{seed}.petacat.jsonl.gz"
    writer = TraceWriter(path)
    writer.write(header_record(problem, seed, cap, replay_of=Path(metacat).name))
    rng = ReplayRNG(seed, trace, writer, complemented_sites=complemented_sites)
    outcome = run_faithful(problem, seed, cap, rng)
    _finish(writer, rng, outcome)
    return path, outcome, rng


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m tests.lockstep.run_trace")
    sub = ap.add_subparsers(dest="command", required=True)
    rec = sub.add_parser("record", help="record Petacat's own trace")
    rec.add_argument("--problem", nargs=3, metavar=("INITIAL", "MODIFIED", "TARGET"),
                     default=["abc", "abd", "xyz"])
    rec.add_argument("--seed", type=int, required=True)
    rec.add_argument("--cap", type=int, default=DEFAULT_CAP)
    rec.add_argument("--out", help="output directory")
    rep = sub.add_parser("replay", help="replay against a Metacat trace")
    rep.add_argument("--metacat", required=True, help="<seed>.metacat.jsonl[.gz]")
    rep.add_argument("--out", help="output directory (default: beside the trace)")
    rep.add_argument("--cap", type=int)
    args = ap.parse_args(argv)

    if args.command == "record":
        path, outcome = record_trace(tuple(args.problem), args.seed, args.cap, args.out)
        print(json.dumps({"trace": str(path), "end": outcome.record()}))
    else:
        path, outcome, rng = replay_trace(args.metacat, args.out, args.cap)
        print(json.dumps({"trace": str(path), "end": outcome.record(),
                          "summary": rng.summary(),
                          "fatal": (outcome.fatal.fatal_class, outcome.fatal.detail)
                          if outcome.fatal else None}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
