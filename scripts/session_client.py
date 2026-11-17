#!/usr/bin/env python3
"""Drive a Training Mode Session over the REST API: the reference for how an ML layer would use Petacat.

The workflow (the user's own): create a Training Mode Session with N problems (default 25) and start it, then,
whenever at least K of them have finished (default 5), add K new ones, until a total is
reached.  It follows the ``finished`` long-poll cursor, so it learns of each finished
problem the moment it finishes, and it prints a line for each.

    .venv/bin/python scripts/session_client.py --url http://127.0.0.1:8765 \\
        --initial 25 --add 5 --total 60 --seeds 8 --max-codelets 2000

Problems come from ``seed_data/demo_problems.json`` plus generated variants
(``abc -> abd`` against a window of the alphabet), or from ``--problems FILE`` (a UTF-8 JSON list
of ``{initial, modified, target, answer?, seeds?, tag?, multi_turn?}``).  Only the standard library is used.

The teacher
-----------
``--teacher SERIES.json`` makes the script the **teacher** of multi-turn runs (Training Mode only): it creates
a session from the problems of the series file (or, with ``--session ID``, follows one that exists and matches
the file's problems by their three strings), starts it, and, for as long as any run is waiting for input, supplies the
next input of each waiting run through ``POST .../runs/{seed}/input``, then ends the run with the series's label
once its inputs are used up.  It follows along by polling.  The series file is plain data, a JSON object (or just
its ``problems`` list)::

    {"problems": [
      {"initial": "abc", "modified": "abd", "target": "ijk", "seeds": 5,
       "inputs": ["xyz", "mno"], "end_label": "series over", "tag": "optional"}
    ]}

``inputs`` are the inputs of turns 2, 3, ... of every run of that problem, in order (any UTF-8 text, kept
exactly); after the last one the run ends, with ``end_label`` (optional).  A problem in a series file is multi-turn
by that fact.  ``seeds`` and ``tag`` are the problem's, as in the problems file.  Every run's conversation is
printed, and ``--out FILE`` writes them all as JSON (it refuses to overwrite).  Example::

    .venv/bin/python scripts/session_client.py --url http://127.0.0.1:8765 \\
        --teacher series.json --seeds 5 --max-codelets 3000 --out conversations.json
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
        with open(path, encoding="utf-8") as fh:
            for p in json.load(fh):
                if fresh(p):
                    yield p
    else:
        with open(os.path.join(REPO, "seed_data", "demo_problems.json"), encoding="utf-8") as fh:
            for d in json.load(fh):
                p = {"initial": d["initial"], "modified": d["modified"], "target": d["target"],
                     "tag": {"demo": d["name"]}}
                if d.get("answer") is not None:
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


def load_series(path: str) -> list[dict]:
    """The problems of a series file, each as a request problem plus ``inputs`` and ``end_label``."""
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    problems = data["problems"] if isinstance(data, dict) else data
    out = []
    for p in problems:
        for key in ("initial", "modified", "target"):
            if not isinstance(p.get(key), str) or p[key] == "":
                raise SystemExit(f"series file: every problem needs a non-empty text {key!r}: {p}")
        inputs = p.get("inputs", [])
        if not isinstance(inputs, list) or not all(isinstance(t, str) and t for t in inputs):
            raise SystemExit(f"series file: `inputs` is a list of non-empty texts: {p}")
        out.append(dict(p, inputs=inputs))
    return out


def series_key(p: dict) -> tuple:
    return (p["initial"], p["modified"], p["target"])


def teach(url: str, tid: int, series: list[dict], timeout: float, poll: float = 0.2) -> list[dict]:
    """Be the teacher of session *tid*: supply each waiting run's next input from *series* (matched to the
    session's problems by their three strings), and end the run when its inputs are used up.  Returns every
    run's conversation once the session has nothing left to run or wait for."""
    base = f"/api/training-mode/sessions/{tid}"
    by_key = {series_key(p): p for p in series}
    started = time.monotonic()
    while True:
        if time.monotonic() - started > timeout:
            raise SystemExit("timed out")
        summary = call(url, "GET", base)
        problems = call(url, "GET", f"{base}/problems?limit=1000")["problems"]
        for p in problems:
            mine = by_key.get(series_key(p))
            if mine is None or p["status"] in ("finished", "cancelled"):
                continue
            for run in call(url, "GET", f"{base}/problems/{p['id']}/runs")["runs"]:
                if run.get("state") != "waiting":
                    continue
                turn = run["waiting_for"]
                at = turn - 2
                body = ({"turn": turn, "text": mine["inputs"][at]} if at < len(mine["inputs"])
                        else {"turn": turn, "end": True, **({"label": mine["end_label"]} if mine.get("end_label") else {})})
                call(url, "POST", f"{base}/problems/{p['id']}/runs/{run['seed']}/input", body)
        if summary["state"] == "running" and summary["activity"] == "idle":
            break
        time.sleep(poll)
    out = []
    for p in call(url, "GET", f"{base}/problems?limit=1000")["problems"]:
        if p["multi_turn"]:
            for run in call(url, "GET", f"{base}/problems/{p['id']}/runs")["runs"]:
                out.append(call(url, "GET", f"{base}/problems/{p['id']}/runs/{run['seed']}"))
    return out


def print_conversation(c: dict) -> None:
    head = f"problem {c['problem_id']} seed {c['seed']}: {c['state']}"
    if c["end_reason"]:
        head += f" ({c['end_reason']}" + (f": {c['end_label']}" if c["end_label"] else "") + ")"
    print(head)
    for t in c["turns"]:
        pos = t["positions"]
        print(f"  turn {t['turn']}: {pos['context']!r} : {pos['second']!r} :: {pos['input']!r} : "
              f"{pos['response']!r}  [{t['status']}, {t['codelets']} codelets]")


def teacher_main(args: argparse.Namespace) -> int:
    if args.out and os.path.exists(args.out):
        raise SystemExit(f"{args.out} exists; refusing to overwrite it")
    series = load_series(args.teacher)
    if args.session:
        tid = args.session
        call(args.url, "POST", f"/api/training-mode/sessions/{tid}/start")
    else:
        settings = {"seeds_per_problem": args.seeds, "max_codelets": args.max_codelets,
                    "seed_start": args.seed_start}
        if args.backend:
            settings["backend"] = args.backend
        if args.configuration_base:
            settings["configuration_base"] = args.configuration_base
        problems = [{k: v for k, v in p.items() if k not in ("inputs", "end_label")} | {"multi_turn": True}
                    for p in series]
        made = call(args.url, "POST", "/api/training-mode/sessions",
                    {"name": args.name, "settings": settings, "problems": problems})
        tid = made["session"]["id"]
        call(args.url, "POST", f"/api/training-mode/sessions/{tid}/start")
    print(f"session {tid}: teaching {len(series)} problem(s)")
    conversations = teach(args.url, tid, series, args.timeout)
    for c in conversations:
        print_conversation(c)
    if args.out:
        with open(args.out, "x", encoding="utf-8") as fh:
            json.dump(conversations, fh, ensure_ascii=False, indent=1)
    call(args.url, "POST", f"/api/training-mode/sessions/{tid}/stop")
    print(f"done: {len(conversations)} runs")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", default="http://127.0.0.1:8765")
    ap.add_argument("--name", default="session_client demo")
    ap.add_argument("--initial", type=int, default=25, help="problems to start with")
    ap.add_argument("--add", type=int, default=5, help="add this many whenever this many have finished")
    ap.add_argument("--total", type=int, default=60, help="stop adding at this many problems")
    ap.add_argument("--seeds", type=int, default=10, help="seeds per problem")
    ap.add_argument("--max-codelets", type=int, default=2000)
    ap.add_argument("--problems", help="JSON file of problems instead of the built-in supply")
    ap.add_argument("--timeout", type=float, default=3600.0)
    ap.add_argument("--teacher", metavar="SERIES.json",
                    help="be the teacher of multi-turn runs from this series file (see above)")
    ap.add_argument("--session", type=int, help="with --teacher: follow this existing session instead of creating one")
    ap.add_argument("--seed-start", type=int, default=1, help="with --teacher: the first seed")
    ap.add_argument("--backend", help="with --teacher: the numeric backend (off, python, numpy, ...)")
    ap.add_argument("--configuration-base", help="with --teacher: the session's configuration base (default training-v2)")
    ap.add_argument("--out", help="with --teacher: write every conversation to this JSON file (not overwritten)")
    args = ap.parse_args()
    if args.teacher:
        return teacher_main(args)

    supply = problem_stream(args.problems)
    started = time.monotonic()
    made = call(args.url, "POST", "/api/training-mode/sessions", {
        "name": args.name,
        "settings": {"seeds_per_problem": args.seeds, "max_codelets": args.max_codelets},
        "problems": [next(supply) for _ in range(args.initial)],
    })
    tid = made["session"]["id"]
    call(args.url, "POST", f"/api/training-mode/sessions/{tid}/start")  # a new Training Mode Session is Stopped
    ex = call(args.url, "GET", "/api/training-mode/sessions")["executor"]
    print(f"session {tid}: {args.initial} problems x {args.seeds} seeds, "
          f"executor={ex['kind']} x{ex['workers']}, backend={made['session']['settings']['backend']}")

    total, cursor, unreplaced, finished = args.initial, 0, 0, 0
    while finished < total or total < args.total:
        if time.monotonic() - started > args.timeout:
            raise SystemExit("timed out")
        data = call(args.url, "GET", f"/api/training-mode/sessions/{tid}/finished?after={cursor}&wait=20", timeout=60)
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
            call(args.url, "POST", f"/api/training-mode/sessions/{tid}/problems", {"problems": [next(supply) for _ in range(n)]})
            total += n
            unreplaced -= args.add
            print(f"           added {n} problems ({total} of {args.total})")
        if total >= args.total and finished >= total:
            break

    call(args.url, "POST", f"/api/training-mode/sessions/{tid}/stop")
    summary = call(args.url, "GET", f"/api/training-mode/sessions/{tid}")
    wall = time.monotonic() - started
    runs = summary["runs"]["done"]
    mem = summary["memory"]
    print(f"done: {summary['problems']['finished']} problems, {runs} runs in {wall:.1f}s "
          f"= {runs / wall:.1f} runs/s, {summary['codelets'] / wall:,.0f} codelets/s, "
          f"errors {summary['runs']['errors']}, capped {summary['runs']['capped']}"
          + f", Episodic Memory v{summary['memory_version']}: {mem['answers']} answers, {mem['snags']} snags")
    return 0


if __name__ == "__main__":
    sys.exit(main())
