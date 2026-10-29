#!/usr/bin/env python3
"""Compare the English Metacat writes for its rules with Petacat's, rule for rule.

Reproduces the check behind ``tests/seed_unit/rule_english_metacat.tsv`` (12,582 of 12,582
Metacat rules transcribed identically).  Metacat 1.2 is run by
``tests/lockstep/metacat/record_rule_english.py`` (every rule's type, clause structure,
text and the codelet count it was built at).  Petacat builds the same rules two ways:

* where the lockstep trace ``<traces>/<slug>/<seed>.metacat.jsonl.gz`` exists, by replaying
  Metacat's recorded decisions (``ReplayRNG``), so Petacat builds the very same rules at the
  same codelets.  The comparison is exact: each Metacat rule is paired with Petacat's rule at
  the same (codelet, type, structure) and the texts must be equal;
* otherwise by a live faithful-mode run with Petacat's own RNG, which does not reproduce
  Metacat's rules one for one.  The comparison there is by structure: for every
  (type, structure) both sides built, the sets of texts must be equal.

    python3 scripts/compare_rule_english.py                         # the committed problem list
    python3 scripts/compare_rule_english.py --problems FILE --jobs 2 --table OUT.tsv
    python3 scripts/compare_rule_english.py --problems FILE --limit 1   # first entry only

``--table PATH`` also writes the distinct-rows fixture from the Metacat side (as
``record_rule_english.py --table`` does).  Needs Docker, the ``metacat:1.2`` image and the
lockstep traces (``record.py``).  The full list takes about 7 minutes with ``--jobs 2``.
Exit status 1 if any text differs or a Metacat rule has no Petacat counterpart.
"""

from __future__ import annotations

import argparse
import collections
import concurrent.futures
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests" / "lockstep" / "metacat"))

import record_rule_english as recorder  # noqa: E402

DEFAULT_PROBLEMS = ROOT / "tests" / "seed_unit" / "rule_english_problems.txt"
DEFAULT_TRACES = ROOT / "tests" / "lockstep" / "traces"


# --- pure logic (tests/lockstep/test_compare_rule_english.py) ----------------------


def parse_rules(lines):
    """RULE lines -> ``{seed: [(codelet, type, key, text), ...]}``; END lines are skipped."""
    runs: dict = collections.OrderedDict()
    for line in lines:
        f = line.rstrip("\n").split("\t")
        if f[0] == "RULE":
            runs.setdefault(int(f[1]), []).append((int(f[2]), f[3], f[4], f[5]))
        elif f[0] == "END":
            runs.setdefault(int(f[1]), [])
    return runs


def compare_exact(metacat, petacat):
    """Pair each Metacat rule with Petacat's at the same (codelet, type, key).

    Returns ``(total, matched, mismatches, unpaired, extra)``: Metacat rules, texts equal,
    ``(metacat rule, petacat texts)`` pairs whose text differs, Metacat rules Petacat did not
    build at that codelet with that structure, and Petacat rules Metacat did not build.
    """
    by_key = collections.defaultdict(list)
    for r in petacat:
        by_key[r[:3]].append(r[3])
    total = matched = unpaired = 0
    mismatches = []
    for r in metacat:
        total += 1
        texts = by_key.get(r[:3])
        if texts is None:
            unpaired += 1
        elif r[3] in texts:
            matched += 1
        else:
            mismatches.append((r, texts))
    keys = {r[:3] for r in metacat}
    extra = sum(1 for r in petacat if r[:3] not in keys)
    return total, matched, mismatches, unpaired, extra


def compare_sets(metacat, petacat):
    """For each (type, key) on both sides, the text sets must be equal.

    Returns ``(both, mismatches, petacat_only)``: structures built by both, the
    ``(structure, metacat texts, petacat texts)`` that differ, and structures only Petacat built.
    """
    def texts(rules):
        d = collections.defaultdict(set)
        for _c, t, k, x in rules:
            d[(t, k)].add(x)
        return d
    m, p = texts(metacat), texts(petacat)
    both = set(m) & set(p)
    bad = [(s, m[s], p[s]) for s in sorted(both) if m[s] != p[s]]
    return len(both), bad, len(set(p) - set(m))


# --- Petacat side -------------------------------------------------------------------


def _name(x):
    if x is None:
        return "#f"
    return x if isinstance(x, str) else x.name


def _od_key(od):
    return f"{_name(od[0])}/{_name(od[1])}/{_name(od[2])}"


def clause_key(c) -> str:
    """The clause key of ``record_rule_english.py`` for one Petacat ``RuleClause``."""
    if c.is_verbatim:
        return "V[" + ",".join(_name(x) for x in c.verbatim_letters) + "]"
    if c.is_extrinsic:
        return ("X[" + ";".join(_od_key(o) for o in c.object_descriptions) + "]["
                + ",".join(_name(d) for d in c.dimensions) + "]")
    return "I[" + _od_key(c.object_descriptions[0]) + "][" + ";".join(
        f"{ch.referent}:{_name(ch.dimension)}:"
        f"{_name(ch.relation if ch.relation is not None else ch.to_descriptor)}"
        for ch in c.changes) + "]"


def petacat_rules(problem, seed, trace):
    """Petacat's RULE lines for one run: a replay of ``trace`` when given, else a live run."""
    import server.engine.rule_english as RE
    from server.engine.runner import EngineRunner

    current: dict = {}
    original_init = EngineRunner.init_mcat

    def init(self, *a, **k):
        current["r"] = self
        return original_init(self, *a, **k)

    lines: list[str] = []
    original = RE.transcribe_rule_to_english_lines

    def hook(rule, meta=None):
        out = original(rule, meta)
        r = current.get("r")
        codelet = r.ctx.codelet_count if r and r.ctx else -1
        lines.append("RULE\t%s\t%s\t%s\t%s\t%s" % (
            seed, codelet, rule.rule_type, "&&".join(clause_key(x) for x in rule.clauses),
            "|||".join(out)))
        return out

    EngineRunner.init_mcat = init
    RE.transcribe_rule_to_english_lines = hook
    try:
        if trace is not None:
            from tests.lockstep.run_trace import replay_trace
            with tempfile.TemporaryDirectory() as d:
                replay_trace(trace, d)
        else:
            from server.engine.rng import RNG
            from tests.lockstep.faithful import run_faithful
            run_faithful(tuple(problem), seed, 100000, RNG(seed))
    finally:
        EngineRunner.init_mcat = original_init
        RE.transcribe_rule_to_english_lines = original
    return lines


def _petacat_job(args):
    problem, seed, trace = args
    return seed, trace is not None, petacat_rules(problem, seed, trace)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--problems", default=str(DEFAULT_PROBLEMS), help="file of 'I M T LO-HI' lines")
    ap.add_argument("--traces", default=str(DEFAULT_TRACES), help="lockstep trace corpus root")
    ap.add_argument("--limit", type=int, help="only the first N entries of the list")
    ap.add_argument("--jobs", type=int, default=2, help="processes / containers at once (default 2)")
    ap.add_argument("--cap", type=int, default=100000)
    ap.add_argument("--table", help="also write the distinct-rows table (fixture format)")
    args = ap.parse_args()

    entries = recorder.parse_problems(Path(args.problems).read_text())[: args.limit]
    with concurrent.futures.ThreadPoolExecutor(args.jobs) as pool:
        mc_lines = list(pool.map(lambda e: recorder.record(e[0], e[1], args.cap), entries))
    if args.table:
        Path(args.table).parent.mkdir(parents=True, exist_ok=True)
        rows = recorder.table_rows([l for lines in mc_lines for l in lines])
        Path(args.table).write_text(recorder.format_table(rows))
        print(f"{args.table}: {len(rows)} distinct rows")

    bad = 0
    tot_rules = tot_match = 0
    with concurrent.futures.ProcessPoolExecutor(args.jobs) as pool:
        for (problem, seeds), lines in zip(entries, mc_lines):
            slug = "-".join(problem)
            metacat = parse_rules(lines)
            jobs = []
            for s in seeds:
                trace = Path(args.traces) / slug / f"{s}.metacat.jsonl.gz"
                jobs.append((problem, s, trace if trace.exists() else None))
            exact = [], []   # (metacat, petacat) rules of replayed runs
            live = [], []
            for seed, replayed, pl in pool.map(_petacat_job, jobs):
                pc = parse_rules(pl).get(seed, [])
                side = exact if replayed else live
                side[0].extend(metacat.get(seed, []))
                side[1].extend(pc)
            total = matched = 0
            if exact[0] or exact[1]:
                total, matched, mism, unp, extra = compare_exact(*exact)
                print(f"{slug}: replayed, {matched}/{total} Metacat rules matched "
                      f"({len(mism)} text mismatches, {unp} unpaired, {extra} Petacat extra)")
                for r, texts in mism[:3]:
                    print("  Metacat:", r, "\n  Petacat:", texts)
                bad += len(mism) + unp
            if live[0] or live[1]:
                both, mism, ponly = compare_sets(*live)
                print(f"{slug}: live, {both} structures built by both, {len(mism)} with different "
                      f"texts, {ponly} Petacat-only")
                for s, m, p in mism[:3]:
                    print("  structure:", s, "\n  Metacat:", m, "\n  Petacat:", p)
                bad += len(mism)
            tot_rules += total
            tot_match += matched
    print(f"total (replayed runs): {tot_match}/{tot_rules} Metacat rules matched")
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
