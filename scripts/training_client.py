#!/usr/bin/env python3
"""Drive a Training over the REST API: the reference for how an ML layer would use Petacat.

The workflow (the user's own): create a Training with N problems (default 25), then,
whenever at least K of them have finished (default 5), add K new ones, until a total is
reached.  It follows the ``finished`` long-poll cursor, so it learns of each finished
problem the moment it finishes, and it prints a line for each.

    .venv/bin/python scripts/training_client.py --url http://127.0.0.1:8765 \\
        --initial 25 --add 5 --total 60 --seeds 8 --max-codelets 2000

Problems come from ``seed_data/demo_problems.json`` plus generated variants
(``abc -> abd`` against a window of the alphabet), or from ``--problems FILE`` (a JSON list
of ``{initial, modified, target, answer?, seeds?, tag?}``).  Only the standard library is used.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ALPHABET = "abcdefghijklmnopqrstuvwxyz"


def call(base: str, method: str, path: str, body: dict | None = None, timeout: float = 90.0):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        base + path, data=data, method=method, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            return json.loads(raw) if raw else None
    except urllib.error.HTTPError as exc:
        raise SystemExit(f"{method} {path} -> {exc.code}: {exc.read().decode()[:300]}")


def problem_stream(path: str | None):
    """An endless supply of distinct problems."""
    seen = set()

    def fresh(p: dict):
        key = (p["initial"], p["modified"], p["target"], p.get("answer"))
        if key in seen:
            return None
        seen.add(key)
        return p

    if path:
        with open(path) as fh:
            for p in json.load(fh):
                if fresh(p):
                    yield p
    else:
        with open(os.path.join(REPO, "seed_data", "demo_problems.json")) as fh:
            for d in json.load(fh):
                p = {"initial": d["initial"], "modified": d["modified"], "target": d["target"],
                     "tag": {"demo": d["name"]}}
                if d["mode"] == "justification":
                    p["answer"] = d["answer"]
                if fresh(p):
                    yield p
    for size in (3, 4, 5, 6):
        for i in range(len(ALPHABET) - size + 1):
            for first, second in (("abc", "abd"), ("abc", "abb"), ("ijk", "ijl"), ("rst", "rsu")):
                p = {"initial": first, "modified": second, "target": ALPHABET[i:i + size],
                     "tag": {"generated": f"{first}>{second}:{ALPHABET[i:i + size]}"}}
                if fresh(p):
                    yield p
    raise SystemExit("out of distinct problems; give --problems or lower --total")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", default="http://127.0.0.1:8765")
    ap.add_argument("--name", default="training_client demo")
    ap.add_argument("--initial", type=int, default=25, help="problems to start with")
    ap.add_argument("--add", type=int, default=5, help="add this many whenever this many have finished")
    ap.add_argument("--total", type=int, default=60, help="stop adding at this many problems")
    ap.add_argument("--seeds", type=int, default=10, help="seeds per problem")
    ap.add_argument("--max-codelets", type=int, default=2000)
    ap.add_argument("--memory", choices=["shared", "independent"], default="shared")
    ap.add_argument("--problems", help="JSON file of problems instead of the built-in supply")
    ap.add_argument("--timeout", type=float, default=3600.0)
    args = ap.parse_args()

    supply = problem_stream(args.problems)
    started = time.monotonic()
    made = call(args.url, "POST", "/api/trainings", {
        "name": args.name,
        "settings": {"memory": args.memory, "seeds_per_problem": args.seeds,
                     "max_codelets": args.max_codelets},
        "problems": [next(supply) for _ in range(args.initial)],
    })
    tid = made["training"]["id"]
    ex = call(args.url, "GET", "/api/trainings")["executor"]
    print(f"training {tid}: {args.initial} problems x {args.seeds} seeds, memory={args.memory}, "
          f"executor={ex['kind']} x{ex['workers']}, backend={made['training']['settings']['backend']}")

    total, cursor, unreplaced, finished = args.initial, 0, 0, 0
    while finished < total or total < args.total:
        if time.monotonic() - started > args.timeout:
            raise SystemExit("timed out")
        data = call(args.url, "GET", f"/api/trainings/{tid}/finished?after={cursor}&wait=20", timeout=60)
        cursor = data["cursor"]
        for p in data["problems"]:
            finished += 1
            unreplaced += 1
            top = p["top"][0] if p["top"] else None
            lead = f"{top['answer']} {top['fraction']:.0%}" if top else "-"
            print(f"[{time.monotonic() - started:7.1f}s] #{p['finished_seq']:>3} "
                  f"{p['initial']}->{p['modified']}, {p['target']:<8} {p['status']:<9} "
                  f"top {lead:<14} distinct {p['distinct']:>2} errors {p['errors']} "
                  f"cap {p['capped']}/{p['runs_done']}")
        while unreplaced >= args.add and total < args.total:
            n = min(args.add, args.total - total)
            call(args.url, "POST", f"/api/trainings/{tid}/problems", {"problems": [next(supply) for _ in range(n)]})
            total += n
            unreplaced -= args.add
            print(f"           added {n} problems ({total} of {args.total})")
        if total >= args.total and finished >= total:
            break

    call(args.url, "POST", f"/api/trainings/{tid}/close")
    summary = call(args.url, "GET", f"/api/trainings/{tid}")
    wall = time.monotonic() - started
    runs = summary["runs"]["done"]
    mem = summary["memory"]
    print(f"done: {summary['problems']['finished']} problems, {runs} runs in {wall:.1f}s "
          f"= {runs / wall:.1f} runs/s, {summary['codelets'] / wall:,.0f} codelets/s, "
          f"errors {summary['runs']['errors']}, capped {summary['runs']['capped']}"
          + (f", memory v{summary['memory_version']}: {mem['answers']} answers, {mem['snags']} snags" if mem else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
