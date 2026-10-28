#!/usr/bin/env python3
"""
Derive the single-run reference sets from the support-v1a study data.

    scripts/make_reference_sets.py

Reads   studies/support-v1a/data/main.tar.gz   (in this repository)

Writes  measurements/reference/single-run-sets.json
        measurements/reference/single-run-p50.json

These are the two files ``scripts/compare_to_metacat.py`` loads for its single-run
mode, in the format Metacat's own ``docker/make_derived_sets.py`` writes. That script
derives them from ``oracle/raw/``, which the Metacat bundle deliberately leaves out
("Measured data are not part of this source reconstruction bundle"), so the comparison
used to need a sibling Metacat checkout. The support-v1a release is Metacat's measured
behaviour in this repository, so the sets are derived from it instead.

WHAT GOES IN

  Every Metacat observation of the construction and validation phases: 20,000 and
  30,000 runs per problem, each from a fresh Episodic Memory at a 100,000-codelet
  cap. The port phase is Petacat and is left out. Only the admitted attempt of each
  chunk is read (its ``complete.json`` receipt), and that attempt's ``runs.jsonl``
  is checked against the receipt's SHA-256 before it is used.

  A run's state is its answer, ``*NONE*`` (gave up), ``*CAP*`` (hit the cap) or
  ``*ERROR*`` (the reference crashed; Metacat/KNOWN-FAILURES.md). A seed observed
  twice in one phase is counted once; the duplicates are the corrected preflight's
  executions, which the study also keeps out of its denominators.

WHAT IS NOT HERE

  The convergence (episodic) sets. A convergence answer is an episode's last run
  that produced an answer, and no study in this repository keeps every run of an
  episode: episodic-v3 records each episode's best answers instead. Its own port
  comparison (studies/episodic-v3) is the in-repository episodic check.

A p50 set is the fewest most-frequent members whose shares reach 50%, each with the
probability that it is absent from a 100-try sample by chance alone, the false-alarm
rate of the "a p50 member went missing" check.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tarfile
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ARCHIVE = os.path.join(ROOT, "studies", "support-v1a", "data", "main.tar.gz")
OUT = os.path.join(ROOT, "measurements", "reference")
PHASES = ("construction", "validation")
N_TEST = 100  # tries per problem in a comparison run


def p50_set(counts, total):
    chosen, cum = [], 0
    for member, c in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])):
        share = c / total
        chosen.append({
            "member": member,
            "count": c,
            "share": round(share, 6),
            f"absence_probability_at_n{N_TEST}": round((1 - share) ** N_TEST, 12),
        })
        cum += c
        if cum / total >= 0.5:
            break
    return chosen


def as_set(counts, total):
    return {m: {"count": c, "share": round(c / total, 6)}
            for m, c in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))}


def state_of(row):
    if row["termination"] == "capped":
        return "*CAP*"
    if row["termination"] == "engine-error":
        return "*ERROR*"
    return row["state"]


def read_observations(archive):
    """``{problem: {"strings": [...], "states": Counter, "per_phase": {...}}}``."""
    with tarfile.open(archive) as tar:
        members = {m.name: m for m in tar if m.isfile()}
        receipts = sorted(name for name in members
                          if name.endswith("/complete.json")
                          and any(f"/chunks/{phase}/" in name for phase in PHASES))
        problems: dict[str, dict] = {}
        seen: set[tuple[str, str, int]] = set()
        duplicates = conflicts = 0
        for receipt_name in receipts:
            receipt = json.load(tar.extractfile(members[receipt_name]))
            task = receipt["task"]
            if task["engine"] != "metacat":
                continue
            runs_name = f"{receipt_name.rsplit('/', 1)[0]}/{receipt['attempt']}/runs.jsonl"
            data = tar.extractfile(members[runs_name]).read()
            if hashlib.sha256(data).hexdigest() != receipt["sha256"]:
                raise SystemExit(f"{runs_name} does not match its receipt")
            entry = problems.setdefault(task["problem"], {
                "strings": task["strings"], "states": Counter(),
                "first": {}, "per_phase": Counter()})
            for line in data.decode().splitlines():
                row = json.loads(line)
                key = (row["phase"], row["problem"], row["seed"])
                state = state_of(row)
                if key in seen:
                    duplicates += 1
                    conflicts += entry["first"][key] != state
                    continue
                seen.add(key)
                entry["first"][key] = state
                entry["states"][state] += 1
                entry["per_phase"][row["phase"]] += 1
        if conflicts:
            raise SystemExit(f"{conflicts} duplicated seeds disagree about their state")
    for entry in problems.values():
        del entry["first"]
    return problems, duplicates


def write(name, payload):
    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, name)
    with open(path, "w") as fh:
        json.dump(payload, fh, indent=2)
        fh.write("\n")
    return path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--archive", default=ARCHIVE)
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    with open(args.archive, "rb") as fh:
        archive_sha = hashlib.sha256(fh.read()).hexdigest()
    problems, duplicates = read_observations(args.archive)

    sets, p50s = [], []
    for name in sorted(problems):
        entry = problems[name]
        counts, n = dict(entry["states"]), sum(entry["states"].values())
        f1 = sum(1 for v in counts.values() if v == 1)
        common = {"name": name, "problem": [name, *entry["strings"]], "n": n}
        sets.append({**common, "runs_per_phase": dict(sorted(entry["per_phase"].items())),
                     "distinct": len(counts), "f1": f1,
                     "f1_over_n": round(f1 / n, 6) if n else None,
                     "set": as_set(counts, n)})
        p50s.append({**common, "p50": p50_set(counts, n)})

    source = {"archive": os.path.relpath(args.archive, ROOT), "sha256": archive_sha,
              "phases": list(PHASES), "duplicate_seeds_dropped": duplicates}
    definition = ("A run's stopping state, from a fresh Episodic Memory at a "
                  "100,000-codelet cap: the answer, *NONE*, *CAP* or *ERROR*. "
                  "Metacat's construction and validation observations of study "
                  "support-v1a; derived by scripts/make_reference_sets.py.")
    paths = [
        write("single-run-sets.json",
              {"source": source, "definition": definition, "results": sets}),
        write("single-run-p50.json",
              {"source": source, "definition": definition,
               "tries_per_problem": N_TEST, "results": p50s}),
    ]
    if args.quiet:
        return 0
    for p in paths:
        print(f"  wrote {os.path.relpath(p, ROOT)}")
    print(f"\n{duplicates} duplicated seeds dropped\n")
    print(f"{'problem':12s} {'runs':>7} {'distinct':>8} {'f1/n':>9}  p50")
    for s, p in zip(sets, p50s):
        print(f"{s['name']:12s} {s['n']:>7} {s['distinct']:>8} {s['f1_over_n']:>9.6f}  "
              + ", ".join(e["member"] for e in p["p50"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
