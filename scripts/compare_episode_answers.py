#!/usr/bin/env python3
"""Compare Metacat's explanation and comparison of an episode's answers with Petacat's.

After an episode of runs with memory carried, Metacat can explain every answer in memory
(the snag explanation it carries, and the two-voice text of the Memory window's "explain")
and compare every ordered pair of answers.  ``tests/lockstep/metacat/record_answers.py`` logs
all three from Metacat 1.2.  Petacat replays the recorded Metacat traces of the same episode
(``tests/lockstep/metacat/record.py --episode-runs 8``), carrying one ``EpisodicMemory``
across the runs, and writes the same three things with ``server.engine.answer_comparison``.

    scripts/compare_episode_answers.py abc-abd-xyz 1-5                     # corpus episodes
    scripts/compare_episode_answers.py abc-abd-ijkk 1-3 --traces DIR       # another corpus root
    scripts/compare_episode_answers.py abc-abd-xyz 1-5 --ignore-order

The comparison is **order-sensitive by default**: the answers must come in the order
Metacat's ``get-answers`` returns them, and so must the explanations and the pairs.  A
different order is reported as ``ORDER`` and fails the run even when every text matches.
``--ignore-order`` compares entry by entry regardless of position (the rule of the first
version of this check).  Needs Docker, the ``metacat:1.2`` image and the episode traces
(``<traces>/episodes/<slug>/<S>.r<k>.metacat.jsonl.gz``; default ``tests/lockstep/traces``).
Metacat's cap is taken from the traces' header unless ``--cap`` is given.  Exit status 1 if
any episode differs.
"""

from __future__ import annotations

import argparse
import collections
import concurrent.futures
import gzip
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests" / "lockstep" / "metacat"))

import record_answers  # noqa: E402
import wrap  # noqa: E402

RUNS_PER_EPISODE = 8
TRACES = ROOT / "tests" / "lockstep" / "traces"
KINDS = ("ANS", "EXPL", "CMP")


def parse_lines(lines) -> dict:
    """``record_answers.py`` output (or its Petacat twin) ->
    ``{"END": [(seed, c, outcome)], "ANS": [(key, snag_explanation)],
    "EXPL": [(key, eliza, technical)], "CMP": [(key_a, key_b, text)]}``, in the order given."""
    out: dict = {"END": [], "ANS": [], "EXPL": [], "CMP": []}
    for line in lines:
        f = line.rstrip("\n").split("\t")
        if f[0] in out:
            out[f[0]].append(tuple(f[1:]))
    return out


def _entry_key(kind: str, entry: tuple) -> tuple:
    """What identifies an entry across the two sides: the answer key (a pair for CMP)."""
    return entry[:2] if kind == "CMP" else entry[:1]


def compare_answers(mc: dict, pc: dict, ignore_order: bool = False) -> dict:
    """Compare two ``parse_lines`` results.

    Returns ``{"total": {kind: n}, "matched": {kind: n}, "order": {kind: bool},
    "problems": [str], "ok": bool}``.  An entry matches when the same key has the same text on
    both sides; ``order[kind]`` is whether the keys come in the same sequence.  Unless
    ``ignore_order`` a different sequence is a problem (``ORDER``) and ``ok`` is false.
    """
    total, matched, order, problems = {}, {}, {}, []
    for kind in KINDS:
        m, p = mc[kind], pc[kind]
        total[kind] = len(m)
        p_by_key = collections.defaultdict(list)
        for e in p:
            p_by_key[_entry_key(kind, e)].append(e)
        n = 0
        for e in m:
            candidates = p_by_key.get(_entry_key(kind, e), [])
            if e in candidates:
                n += 1
                candidates.remove(e)
            else:
                got = candidates[0] if candidates else None
                problems.append(f"{kind} differs\n  Metacat: {e}\n  Petacat: {got}")
        matched[kind] = n
        for key, rest in p_by_key.items():
            for e in rest:
                if not any(_entry_key(kind, x) == key for x in m):
                    problems.append(f"{kind} only in Petacat: {e}")
        order[kind] = [_entry_key(kind, e) for e in m] == [_entry_key(kind, e) for e in p]
        if not order[kind] and not ignore_order:
            problems.append(
                f"ORDER {kind}: Metacat {[_entry_key(kind, e) for e in m][:6]} ... "
                f"Petacat {[_entry_key(kind, e) for e in p][:6]} ..."
            )
    return {"total": total, "matched": matched, "order": order, "problems": problems,
            "ok": not problems}


def trace_cap(first: Path) -> int:
    """The codelet cap in a trace's header record."""
    with gzip.open(first, "rt") as f:
        return int(json.loads(f.readline()).get("cap", 100000))


def petacat_answer_lines(first_trace: Path) -> list[str]:
    """Replay the episode whose first run is ``first_trace``; return ``record_answers.py``-style
    END/ANS/EXPL/CMP lines for the memory it leaves."""
    from server.engine.answer_comparison import (
        compare_answers_text,
        explain_answer,
        snag_explanation_for,
    )
    from server.engine.memory import EpisodicMemory
    from server.engine.metadata import default_commentary_templates
    from tests.lockstep.run_trace import episode_runs, replay_trace

    memory = EpisodicMemory()
    lines = []
    for meta in episode_runs(first_trace):
        stem = ".".join(meta.name.split(".")[:2])
        with tempfile.TemporaryDirectory() as out:
            _, outcome, _ = replay_trace(meta, out, memory=memory, name=stem)
        lines.append(f"END\t{stem}\t{outcome.c}\t{outcome.reason}")
        if outcome.reason in ("error", "fatal"):
            break
    templates = default_commentary_templates()

    def key(a):
        return "%s|%s" % (a.problem[3], "/".join(a.top_rule_description.split("\n")))

    for a in memory.answers:
        lines.append("ANS\t%s\t%s" % (key(a), snag_explanation_for(a, memory, templates)))
        e = explain_answer(a, memory, templates)
        lines.append("EXPL\t%s\t%s\t%s" % (key(a), e["eliza_text"], e["technical_text"]))
    for a in memory.answers:
        for b in memory.answers:
            if a is not b:
                lines.append("CMP\t%s\t%s\t%s" % (
                    key(a), key(b), compare_answers_text(a, b, memory, templates)["text"]))
    return lines


def episode_first_trace(slug: str, seed: int, traces: Path = TRACES) -> Path:
    first = traces / "episodes" / slug / f"{seed}.r1.metacat.jsonl.gz"
    if not first.exists():
        raise FileNotFoundError(first)
    return first


def record_episode(slug: str, seed: int, traces: Path = TRACES, cap: int | None = None,
                   runs: int = RUNS_PER_EPISODE) -> list[str]:
    """Metacat's END/ANS/EXPL/CMP lines for the episode of episode seed ``seed``."""
    first = episode_first_trace(slug, seed, traces)
    return record_answers.record(
        wrap.slug_problem(slug), list(range(seed, seed + runs)), cap or trace_cap(first))


def check_episode(slug: str, seed: int, traces: Path = TRACES, cap: int | None = None,
                  ignore_order: bool = False, runs: int = RUNS_PER_EPISODE,
                  metacat_lines: list[str] | None = None) -> dict:
    """Record (unless ``metacat_lines`` is given), replay in Petacat and compare one episode."""
    first = episode_first_trace(slug, seed, traces)
    if metacat_lines is None:
        metacat_lines = record_episode(slug, seed, traces, cap, runs)
    result = compare_answers(parse_lines(metacat_lines), parse_lines(petacat_answer_lines(first)), ignore_order)
    result["slug"], result["seed"] = slug, seed
    return result


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("slug", help="problem slug i-m-t")
    ap.add_argument("seeds", help="episode seeds, e.g. 1-5")
    ap.add_argument("--traces", default=str(TRACES), help="corpus root holding episodes/<slug>/ (default tests/lockstep/traces)")
    ap.add_argument("--cap", type=int, help="Metacat codelet cap (default: the traces' header)")
    ap.add_argument("--runs", type=int, default=RUNS_PER_EPISODE, help="runs per episode (default 8)")
    ap.add_argument("--ignore-order", action="store_true", help="do not require Metacat's answer order")
    ap.add_argument("--jobs", type=int, default=2, help="Metacat containers in parallel (default 2)")
    args = ap.parse_args(argv)

    seeds = wrap.parse_seeds(args.seeds)
    traces = Path(args.traces)
    # Metacat runs in parallel containers; the Petacat replays share process-wide engine
    # state and run one after the other.
    with concurrent.futures.ThreadPoolExecutor(args.jobs) as pool:
        recorded = list(pool.map(
            lambda s: record_episode(args.slug, s, traces, args.cap, args.runs), seeds))
    results = [check_episode(args.slug, s, traces, args.cap, args.ignore_order, args.runs, lines)
               for s, lines in zip(seeds, recorded)]
    bad = 0
    tot, ok = collections.Counter(), collections.Counter()
    for r in results:
        for k in KINDS:
            tot[k] += r["total"][k]
            ok[k] += r["matched"][k]
        if not r["ok"]:
            bad += 1
            print(f"DIFF {r['slug']} episode {r['seed']}")
            for p in r["problems"][:6]:
                print("  " + p.replace("\n", "\n  "))
    print(f"{args.slug}: {len(results) - bad}/{len(results)} episodes identical"
          f"{' (order ignored)' if args.ignore_order else ' (order-sensitive)'}; "
          + ", ".join(f"{k} {ok[k]}/{tot[k]}" for k in KINDS))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
