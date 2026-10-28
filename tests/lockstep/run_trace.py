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
import os
import sys
from pathlib import Path
from typing import Any

from tests.lockstep.faithful import (
    DEFAULT_CAP, NUMERIC_BACKEND_ENV, Outcome, header_record, run_faithful,
)
from tests.lockstep.replay_rng import MetacatTrace, ReplayRNG
from tests.lockstep.trace_io import TraceWriter
from tests.lockstep.tracing_rng import TracingRNG

TRACES = Path(__file__).resolve().parent / "traces"


def slug(problem: tuple[str, str, str], answer: str | None = None) -> str:
    return "-".join(list(problem) + ([answer] if answer else []))


def _finish(writer: TraceWriter, rng: Any, outcome: Outcome) -> None:
    if outcome.fatal is not None:
        writer.write({"t": "fatal", "class": outcome.fatal.fatal_class, "c": outcome.c,
                      "detail": outcome.fatal.detail})
    writer.write(outcome.record())
    writer.close()


def record_trace(problem: tuple[str, str, str], seed: int, cap: int = DEFAULT_CAP,
                 out_dir: str | Path | None = None, answer: str | None = None,
                 ) -> tuple[Path, Outcome]:
    """Petacat's own trace of one problem and seed (``TracingRNG``)."""
    out = Path(out_dir) if out_dir else TRACES / slug(problem, answer)
    path = out / f"{seed}.petacat.jsonl.gz"
    writer = TraceWriter(path)
    writer.write(header_record(problem, seed, cap, answer=answer))
    rng = TracingRNG(seed, writer)
    outcome = run_faithful(problem, seed, cap, rng, answer=answer)
    _finish(writer, rng, outcome)
    return path, outcome


def record_episode(problem: tuple[str, str, str], episode_seed: int, runs: int,
                   cap: int = DEFAULT_CAP, out_dir: str | Path | None = None,
                   answer: str | None = None) -> list[tuple[Path, Outcome]]:
    """Petacat's own episode: ``runs`` runs, one ``EpisodicMemory`` carried across them,
    run k seeded ``episode_seed + k - 1`` (the collectors' convention).  Writes
    ``<S>.r<k>.petacat.jsonl.gz``.  Stops after an error or fatal."""
    from server.engine.memory import EpisodicMemory

    out = Path(out_dir) if out_dir else TRACES / "episodes" / slug(problem, answer)
    memory, done = EpisodicMemory(), []
    for k in range(1, runs + 1):
        seed = episode_seed + k - 1
        path = out / f"{episode_seed}.r{k}.petacat.jsonl.gz"
        writer = TraceWriter(path)
        writer.write(header_record(problem, seed, cap, answer=answer, episode_run=k,
                                   episode_seed=episode_seed))
        rng = TracingRNG(seed, writer)
        outcome = run_faithful(problem, seed, cap, rng, answer=answer, memory=memory)
        _finish(writer, rng, outcome)
        done.append((path, outcome))
        if outcome.reason in ("error", "fatal"):
            break
    return done


def replay_trace(metacat: str | Path, out_dir: str | Path | None = None,
                 cap: int | None = None, complemented_sites: tuple[str, ...] = (),
                 memory: Any = None, name: str | None = None,
                 header_extra: dict[str, Any] | None = None,
                 ) -> tuple[Path, Outcome, ReplayRNG]:
    """Replay ``metacat`` (a reference trace) in Petacat; returns the trace written.

    A justify-mode trace (header ``answer``) is replayed in justify mode.  ``memory``
    is an episode's carried ``EpisodicMemory`` (see ``replay_episode``); ``name`` is
    the output file's stem (default: the seed).
    """
    trace = MetacatTrace(metacat)
    head = trace.header
    problem = tuple(head["problem"])
    seed = int(head["seed"])
    answer = head.get("answer")
    cap = int(cap if cap is not None else head.get("cap", DEFAULT_CAP))
    out = Path(out_dir) if out_dir else Path(metacat).parent
    path = out / f"{name or seed}.petacat.jsonl.gz"
    extra = {k: head[k] for k in ("episode_run", "episode_seed") if k in head}
    extra.update(header_extra or {})
    writer = TraceWriter(path)
    writer.write(header_record(problem, seed, cap, answer=answer,
                               replay_of=Path(metacat).name, **extra))
    rng = ReplayRNG(seed, trace, writer, complemented_sites=complemented_sites)
    outcome = run_faithful(problem, seed, cap, rng, answer=answer, memory=memory)
    _finish(writer, rng, outcome)
    return path, outcome, rng


def is_episode_run(metacat: str | Path) -> bool:
    """True for ``<S>.r<k>.metacat.jsonl[.gz]``."""
    parts = Path(metacat).name.split(".")
    return len(parts) > 2 and parts[1][:1] == "r" and parts[1][1:].isdigit()


def episode_runs(metacat: str | Path) -> list[Path]:
    """Every run's Metacat trace of the episode ``metacat`` belongs to, in run order.
    ``metacat`` is any of ``<S>.r<k>.metacat.jsonl[.gz]``."""
    path = Path(metacat)
    stem = path.name.split(".")[0]
    runs = []
    for p in path.parent.glob(f"{stem}.r*.metacat.jsonl*"):
        k = p.name.split(".")[1]
        if k[1:].isdigit():
            runs.append((int(k[1:]), p))
    return [p for _, p in sorted(runs)]


def replay_episode(metacat: str | Path, out_dir: str | Path | None = None,
                   cap: int | None = None, complemented_sites: tuple[str, ...] = (),
                   ) -> list[tuple[Path, Outcome | None, ReplayRNG | None]]:
    """Replay an episode run by run with one ``EpisodicMemory`` carried across the
    runs, each run against its own Metacat trace (``<S>.r<k>.metacat``), writing
    ``<S>.r<k>.petacat.jsonl.gz``.

    After a fatal or error in run k the memory no longer matches Metacat's, so the
    later runs are not replayed; each gets a stub trace (header, a ``not-reached``
    fatal, end) and ``(path, None, None)`` is returned for it.  A run whose outcome
    differs from Metacat's (reason or answer) leaves memory out of step with Metacat's:
    later runs are still replayed but their headers say ``memory_in_sync: false``.
    """
    from server.engine.memory import EpisodicMemory

    memory = EpisodicMemory()
    in_sync, stopped, results = True, False, []
    for meta in episode_runs(metacat):
        trace = MetacatTrace(meta)
        head = trace.header
        out = Path(out_dir) if out_dir else meta.parent
        stem = ".".join(meta.name.split(".")[:2])
        if stopped:
            path = out / f"{stem}.petacat.jsonl.gz"
            writer = TraceWriter(path)
            writer.write(header_record(tuple(head["problem"]), int(head["seed"]),
                                       int(head.get("cap", DEFAULT_CAP)),
                                       answer=head.get("answer"), not_reached=True,
                                       replay_of=meta.name,
                                       episode_run=head.get("episode_run"),
                                       episode_seed=head.get("episode_seed")))
            writer.write({"t": "fatal", "class": "not-reached", "c": 0,
                          "detail": "an earlier run of the episode ended in a fatal or error"})
            writer.write({"t": "end", "c": 0, "reason": "fatal"})
            writer.close()
            results.append((path, None, None))
            continue
        path, outcome, rng = replay_trace(meta, out_dir, cap, complemented_sites,
                                          memory=memory, name=stem,
                                          header_extra={"memory_in_sync": in_sync}
                                          if head.get("episode_run", 1) > 1 else None)
        end = trace.end or {}
        same = outcome.reason == end.get("reason") and outcome.answer == end.get("answer")
        results.append((path, outcome, rng))
        in_sync = in_sync and same
        if outcome.reason in ("error", "fatal"):
            stopped = True
    return results


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m tests.lockstep.run_trace")
    sub = ap.add_subparsers(dest="command", required=True)
    rec = sub.add_parser("record", help="record Petacat's own trace")
    rec.add_argument("--problem", nargs=3, metavar=("INITIAL", "MODIFIED", "TARGET"),
                     default=["abc", "abd", "xyz"])
    rec.add_argument("--seed", type=int, required=True)
    rec.add_argument("--answer", help="justify mode: the answer string")
    rec.add_argument("--episode-runs", type=int, default=0, metavar="N",
                     help="record an episode of N runs (seed S+k-1 for run k)")
    rec.add_argument("--cap", type=int, default=DEFAULT_CAP)
    rec.add_argument("--out", help="output directory")
    rep = sub.add_parser("replay", help="replay against a Metacat trace")
    rep.add_argument("--metacat", required=True, help="<seed>.metacat.jsonl[.gz]")
    rep.add_argument("--out", help="output directory (default: beside the trace)")
    rep.add_argument("--cap", type=int)
    rep.add_argument("--episode", action="store_true",
                     help="--metacat is one run (<S>.r<k>) of an episode: replay them all")
    for p in (rec, rep):
        p.add_argument("--numeric-backend", choices=["python", "numpy", "mlx", "mlx-cpu"],
                       help="run with this numeric backend instead of faithful mode's 'off'")
    args = ap.parse_args(argv)
    if args.numeric_backend:
        os.environ[NUMERIC_BACKEND_ENV] = args.numeric_backend

    if args.command == "record" and args.episode_runs:
        for path, outcome in record_episode(tuple(args.problem), args.seed, args.episode_runs,
                                            args.cap, args.out, args.answer):
            print(json.dumps({"trace": str(path), "end": outcome.record()}))
    elif args.command == "record":
        path, outcome = record_trace(tuple(args.problem), args.seed, args.cap, args.out,
                                     args.answer)
        print(json.dumps({"trace": str(path), "end": outcome.record()}))
    elif args.episode or is_episode_run(args.metacat):
        for path, outcome, rng in replay_episode(args.metacat, args.out, args.cap):
            print(json.dumps({"trace": str(path),
                              "end": outcome.record() if outcome else None,
                              "summary": rng.summary() if rng else None,
                              "fatal": (outcome.fatal.fatal_class, outcome.fatal.detail)
                              if outcome and outcome.fatal else None}))
    else:
        path, outcome, rng = replay_trace(args.metacat, args.out, args.cap)
        print(json.dumps({"trace": str(path), "end": outcome.record(),
                          "summary": rng.summary(),
                          "fatal": (outcome.fatal.fatal_class, outcome.fatal.detail)
                          if outcome.fatal else None}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
