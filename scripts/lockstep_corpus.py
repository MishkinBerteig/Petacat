#!/usr/bin/env python3
"""Lockstep corpus driver: replay every recorded Metacat trace in Petacat, compare, and
maintain the ratchet (meta-peta-trace-idea.md sections 10.1 and 10.4).

For every ``tests/lockstep/traces/<slug>/<seed>.metacat.jsonl.gz`` this runs (unless
``--no-replay``)::

    .venv/bin/python -m tests.lockstep.run_trace replay --metacat <path> --out <petacat>

then compares the two traces and prints one row per trace.  ``--update-ratchet``
writes ``tests/lockstep/ratchet.json``; ``--check-ratchet`` exits non-zero when any
trace got worse (reach down, agreement down, unregistered errors up).

Assumed CLI contract: ``run_trace replay --metacat PATH --out PATH``.  Use
``--replay-cmd`` to substitute another command template (``{metacat}``, ``{out}`` -- the
Petacat trace's path -- and ``{outdir}``, its directory
are filled in).
"""

from __future__ import annotations

import argparse
import json
import shlex
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import compare_traces as ct  # noqa: E402

REPO = ct.REPO_ROOT
TRACES = REPO / "tests" / "lockstep" / "traces"
RATCHET = REPO / "tests" / "lockstep" / "ratchet.json"
DEFAULT_OUT = REPO / "tests" / "lockstep" / "replays"
DEFAULT_CMD = ".venv/bin/python -m tests.lockstep.run_trace replay --metacat {metacat} --out {outdir}"
EPS = 1e-12


def _seed_key(seed: str) -> tuple[int, int]:
    """Sort key of ``7`` or an episode run ``7.r3`` (episode seed, run)."""
    head, _, run = seed.partition(".r")
    return (int(head) if head.isdigit() else 0, int(run) if run.isdigit() else 0)


def find_traces(root: Path, problems: list[str] | None = None, seeds: list[str] | None = None,
                kind: str = "single") -> list[tuple[str, str, Path]]:
    """Metacat traces under ``root`` (the traces directory).

    ``kind`` picks the layout: ``single`` -- ``<slug>/<seed>.metacat.jsonl.gz`` (the
    default; episodic and justify traces are not in this glob); ``justify`` --
    ``justify/<slug>/<seed>...``; ``episodes`` -- ``episodes/<slug>/<S>.r<k>...`` (seed
    ``S.rk``; ``--seed S`` selects the whole episode).  The returned slug carries the
    sub-directory (``episodes/abc-abd-xyz``).
    """
    sub = {"single": "", "justify": "justify", "episodes": "episodes"}[kind]
    base = root / sub if sub else root
    out = []
    for p in sorted(base.glob("*/*.metacat.jsonl*")):
        slug, seed = p.parent.name, ".".join(p.name.split(".")[:2] if kind == "episodes" else p.name.split(".")[:1])
        if problems and slug not in problems and f"{sub}/{slug}" not in problems:
            continue
        if seeds and seed not in seeds and seed.split(".")[0] not in seeds:
            continue
        out.append((f"{sub}/{slug}" if sub else slug, seed, p))
    return sorted(out, key=lambda t: (t[0], _seed_key(t[1])))


def petacat_path(out_dir: Path, slug: str, seed: str) -> Path:
    return out_dir / slug / f"{seed}.petacat.jsonl.gz"


def _header(path: Path) -> dict:
    import gzip
    try:
        with (gzip.open(path, "rt") if path.suffix == ".gz" else open(path)) as f:
            return json.loads(f.readline())
    except (OSError, ValueError):
        return {}


def replay(metacat: Path, out: Path, cmd_template: str) -> tuple[bool, str]:
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = shlex.split(cmd_template.format(metacat=shlex.quote(str(metacat)), out=shlex.quote(str(out)),
                                           outdir=shlex.quote(str(out.parent))))
    r = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True)
    return r.returncode == 0 or out.exists(), (r.stderr or r.stdout)[-400:]


def summarise(slug: str, seed: str, meta: Path, pet: Path, registry: ct.Registry) -> dict:
    rep = ct.compare(meta, pet, registry)
    ff = rep.first_fatal
    return {
        "memory_in_sync": _header(pet).get("memory_in_sync", True),
        "not_reached": bool(_header(pet).get("not_reached")),
        "key": f"{slug}/{seed}", "problem": slug, "seed": seed,
        "reach": rep.reach, "run_length": rep.run_length,
        "agreement": rep.agreement, "unregistered_errors": rep.unregistered_error_count,
        "first_fatal": f"{ff.klass} {((ff.petacat or ff.metacat or {}).get('site') or '-')}" if ff else "-",
    }


def ratchet_regressions(old: dict, new: dict) -> list[str]:
    """Human-readable list of traces that got worse (or vanished) versus ``old``."""
    bad = []
    for key, o in sorted(old.items()):
        n = new.get(key)
        if n is None:
            bad.append(f"{key}: missing from the new results")
            continue
        if n["reach"] < o["reach"]:
            bad.append(f"{key}: reach {o['reach']} -> {n['reach']}")
        if n["agreement"] < o["agreement"] - EPS:
            bad.append(f"{key}: agreement {o['agreement']:.6f} -> {n['agreement']:.6f}")
        if n["unregistered_errors"] > o["unregistered_errors"]:
            bad.append(f"{key}: unregistered errors {o['unregistered_errors']} -> {n['unregistered_errors']}")
    return bad


def to_ratchet(rows: list[dict]) -> dict:
    return {r["key"]: {"reach": r["reach"], "agreement": r["agreement"],
                       "unregistered_errors": r["unregistered_errors"]} for r in rows}


def print_table(rows: list[dict]) -> None:
    print(f"{'problem':32s} {'seed':>8s} {'reach':>8s} {'length':>8s} {'agree':>7s} {'errors':>7s}  first fatal")
    for r in rows:
        note = " (not reached)" if r.get("not_reached") else "" if r.get("memory_in_sync", True) else " (memory out of step)"
        print(f"{r['problem']:32s} {r['seed']:>8s} {r['reach']:>8d} {r['run_length']:>8d} "
              f"{r['agreement']:7.4f} {r['unregistered_errors']:>7d}  {r['first_fatal']}{note}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--traces", default=str(TRACES))
    ap.add_argument("--out-dir", default=str(DEFAULT_OUT), help="where Petacat replay traces are written/read")
    ap.add_argument("--problem", action="append", help="restrict to a problem slug (repeatable)")
    ap.add_argument("--seed", action="append", help="restrict to a seed (repeatable)")
    ap.add_argument("--no-replay", action="store_true", help="compare existing Petacat traces in --out-dir")
    ap.add_argument("--replay-cmd", default=DEFAULT_CMD)
    ap.add_argument("--jobs", type=int, default=1)
    ap.add_argument("--registry", default=str(ct.DEFAULT_REGISTRY))
    ap.add_argument("--episodes", action="store_true",
                    help="replay the episode traces (traces/episodes/<slug>/<S>.r<k>...) instead: one "
                         "replay per episode, one memory carried across its runs; ratchet-episodes.json")
    ap.add_argument("--justify", action="store_true",
                    help="replay the justify-mode traces (traces/justify/<slug>/<seed>...); ratchet-justify.json")
    ap.add_argument("--ratchet", default=None)
    ap.add_argument("--update-ratchet", action="store_true")
    ap.add_argument("--check-ratchet", action="store_true")
    args = ap.parse_args(argv)

    if args.episodes and args.justify:
        ap.error("--episodes and --justify are separate corpora; run them one at a time")
    kind = "episodes" if args.episodes else "justify" if args.justify else "single"
    if args.ratchet is None:
        args.ratchet = str(RATCHET.with_name({"single": "ratchet.json", "episodes": "ratchet-episodes.json",
                                              "justify": "ratchet-justify.json"}[kind]))
    traces = find_traces(Path(args.traces), args.problem, args.seed, kind)
    if not traces:
        print(f"no traces under {args.traces}", file=sys.stderr)
        return 2
    out_dir = Path(args.out_dir)
    registry = ct.Registry.load(args.registry)

    # A unit of work is one replay command: one trace, or (episodes) all runs of an episode.
    units: dict[tuple, list] = {}
    for item in traces:
        key = (item[0], item[1].split(".")[0]) if kind == "episodes" else (item[0], item[1])
        units.setdefault(key, []).append(item)

    def work(group):
        out = []
        first = group[0]
        if not args.no_replay:
            ok, msg = replay(first[2], petacat_path(out_dir, first[0], first[1]), args.replay_cmd)
            if not ok:
                return [(it, None, f"replay failed: {msg}") for it in group]
        for item in group:
            slug, seed, meta = item
            pet = petacat_path(out_dir, slug, seed)
            if not pet.exists():
                out.append((item, None, f"no petacat trace at {pet}"))
            else:
                out.append((item, summarise(slug, seed, meta, pet, registry), None))
        return out

    with ThreadPoolExecutor(max_workers=max(1, args.jobs)) as ex:
        results = [r for part in ex.map(work, units.values()) for r in part]
    rows, failures = [], []
    for item, row, err in results:
        if err:
            failures.append(f"{item[0]}/{item[1]}: {err}")
        else:
            rows.append(row)
    print_table(rows)
    for f in failures:
        print("ERROR", f, file=sys.stderr)

    rc = 1 if failures else 0
    new = to_ratchet(rows)
    ratchet = Path(args.ratchet)
    if args.check_ratchet:
        old = json.loads(ratchet.read_text()) if ratchet.exists() else {}
        regress = ratchet_regressions(old, new) if not args.problem and not args.seed else \
            ratchet_regressions({k: v for k, v in old.items() if k in new}, new)
        for r in regress:
            print("REGRESSION", r, file=sys.stderr)
        if regress:
            rc = 1
    if args.update_ratchet:
        if failures:
            print("not updating the ratchet: some traces failed", file=sys.stderr)
        else:
            merged = json.loads(ratchet.read_text()) if ratchet.exists() and (args.problem or args.seed) else {}
            merged.update(new)
            ratchet.write_text(json.dumps(merged, indent=1, sort_keys=True) + "\n")
            print(f"wrote {ratchet}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
