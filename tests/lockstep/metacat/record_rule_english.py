#!/usr/bin/env python3
"""Log the English Metacat 1.2 writes for every rule it makes.

Reproduces the data of ``tests/seed_unit/rule_english_metacat.tsv``.  Metacat's
``transcribe-to-english`` (``rules.ss``) describes each rule the moment it is built; this
recorder wraps it in the unpatched ``metacat:1.2`` container (``set!`` of the top-level
procedure, see README.md), runs the problem for each seed with memory cleared, and prints

    RULE<TAB>seed<TAB>codelet-count<TAB>rule-type<TAB>clause-key<TAB>line1|||line2...
    END<TAB>seed<TAB>codelet-count<TAB>outcome

``clause-key`` writes the rule's clauses in a form the Petacat side reproduces from its own
``Rule`` (``V[letters]``, ``X[object-descriptions][dimensions]``,
``I[object-description][referent:dimension:relation;...]``, clauses joined by ``&&``, slipnet
nodes by their ``plato-`` name).  ``scripts/compare_rule_english.py`` compares it with
Petacat's transcription of the same rules.

    python3 tests/lockstep/metacat/record_rule_english.py abc abd xyz 1-10
    python3 tests/lockstep/metacat/record_rule_english.py --problems tests/seed_unit/rule_english_problems.txt \\
        --jobs 2 --table tests/lockstep/out/rule_english_metacat.tsv

``--problems FILE`` records every ``I M T LO-HI`` line of FILE (one container each,
``--jobs`` at a time) into ``--out`` (default ``tests/lockstep/out/rule-english/``), one
``<I>-<M>-<T>.<LO>-<HI>.tsv`` per entry.  ``--table PATH`` also writes the distinct
(rule type, clause structure with ``plato-`` dropped, text) rows, sorted: the committed
fixture's format.  The full list takes about 3-4 minutes with ``--jobs 2``.
Needs Docker and the ``metacat:1.2`` image.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import wrap  # noqa: E402

TABLE_HEADER = (
    "# Metacat 1.2's transcribe-to-english, recorded: rule type, clause structure (plato- "
    "prefixes dropped), the lines Metacat printed joined by |||.\n"
    "# Rules made over the problems of tests/seed_unit/rule_english_problems.txt; regenerate with\n"
    "#   python3 tests/lockstep/metacat/record_rule_english.py --problems "
    "tests/seed_unit/rule_english_problems.txt --jobs 2 --table <path>\n"
    "# and compare with Petacat: scripts/compare_rule_english.py; see tests/seed_unit/test_rule_english.py.\n"
)

DRIVER_BODY = r'''(define cur-seed 0)
(define (nm x) (cond ((symbol? x) (symbol->string x)) ((not x) "#f") (else (symbol->string (tell x 'get-name-symbol)))))
(define (join-with sep l)
  (if (null? l) "" (apply string-append (car l) (map (lambda (x) (string-append sep x)) (cdr l)))))
(define (od-key od) (format "~a/~a/~a" (nm (1st od)) (nm (2nd od)) (nm (3rd od))))
(define (clause-key c)
  (record-case c
    (verbatim (lcs) (format "V[~a]" (join-with "," (map nm lcs))))
    (extrinsic (ods dims) (format "X[~a][~a]" (join-with ";" (map od-key ods)) (join-with "," (map nm dims))))
    (intrinsic (ods changes)
      (format "I[~a][~a]" (od-key (1st ods))
        (join-with ";" (map (lambda (ch) (format "~a:~a:~a" (nm (1st ch)) (nm (2nd ch)) (nm (3rd ch)))) changes))))))
(define orig-transcribe transcribe-to-english)
(set! transcribe-to-english
  (lambda (rule-type clauses)
    (let ((r (orig-transcribe rule-type clauses)))
      (display (format "RULE\t~a\t~a\t~a\t~a\t~a" cur-seed *codelet-count* rule-type
                 (join-with "&&" (map clause-key clauses))
                 (join-with "|||" r)))
      (write-char #\newline)
      r)))
(define (one-run run-seed)
  (set! cur-seed run-seed)
  (tell *memory* 'clear)
  (let* ((outcome
           (guard (c (#t 'error))
             (init-mcat 'I 'M 'T #f run-seed)
             (set! *break-time* CAP)
             (call/cc (lambda (k)
                        (set! suspend (lambda () (k 'suspended)))
                        (set! break (lambda () (k 'capped)))
                        (run-mcat))))))
    (display (format "END\t~a\t~a\t~a" run-seed *codelet-count* outcome))
    (write-char #\newline)))
'''


def driver_text(problem: list[str], seeds: list[int], cap: int) -> str:
    body = DRIVER_BODY.replace("'I 'M 'T", "'{} '{} '{}".format(*problem)).replace("CAP", str(cap))
    return wrap.PRELUDE + body + "".join(f"(one-run {s})\n" for s in seeds) + "(exit 0)\n"


def record(problem: list[str], seeds: list[int], cap: int = 100000) -> list[str]:
    """The RULE and END lines of one container run."""
    out = wrap.run_driver(driver_text(problem, seeds, cap), "english-" + "-".join(problem))
    return wrap.keep_lines(out, "RULE\t", "END\t")


def parse_problems(text: str) -> list[tuple[list[str], list[int]]]:
    """``I M T LO-HI`` lines (``#`` comments and blank lines skipped) -> (problem, seeds)."""
    entries = []
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        i, m, t, seeds = line.split()
        entries.append(([i, m, t], wrap.parse_seeds(seeds)))
    return entries


def table_rows(lines: list[str]) -> list[tuple[str, str, str]]:
    """Distinct sorted (rule type, clause key without ``plato-``, text) of the RULE lines."""
    rows = set()
    for line in lines:
        f = line.rstrip("\n").split("\t")
        if f[0] == "RULE":
            rows.add((f[3], f[4].replace("plato-", ""), f[5]))
    return sorted(rows)


def format_table(rows: list[tuple[str, str, str]]) -> str:
    return TABLE_HEADER + "".join("\t".join(r) + "\n" for r in rows)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("problem", nargs="*", help="initial modified target, then seeds LO-HI")
    ap.add_argument("--problems", help="file of 'I M T LO-HI' lines instead of one problem")
    ap.add_argument("--cap", type=int, default=100000, help="codelet cap (default 100000)")
    ap.add_argument("--jobs", type=int, default=2, help="containers at once (default 2)")
    ap.add_argument("--out", default=str(wrap.DEFAULT_OUT / "rule-english"))
    ap.add_argument("--table", help="also write the distinct-rows table (the fixture format)")
    args = ap.parse_args()

    if args.problems:
        entries = parse_problems(Path(args.problems).read_text())
    elif len(args.problem) == 4:
        entries = [(args.problem[:3], wrap.parse_seeds(args.problem[3]))]
    else:
        ap.error("give 'I M T LO-HI' or --problems FILE")

    with concurrent.futures.ThreadPoolExecutor(args.jobs) as pool:
        results = list(pool.map(lambda e: record(e[0], e[1], args.cap), entries))
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    everything: list[str] = []
    for (problem, seeds), lines in zip(entries, results):
        name = f"{'-'.join(problem)}.{seeds[0]}-{seeds[-1]}.tsv"
        (out / name).write_text("".join(l + "\n" for l in lines))
        everything += lines
        rules = sum(1 for l in lines if l.startswith("RULE"))
        print(f"{name}: {rules} rules, {sum(1 for l in lines if l.startswith('END'))}/{len(seeds)} runs")
    if args.table:
        Path(args.table).parent.mkdir(parents=True, exist_ok=True)
        rows = table_rows(everything)
        Path(args.table).write_text(format_table(rows))
        print(f"{args.table}: {len(rows)} distinct rows")
    return 0


if __name__ == "__main__":
    sys.exit(main())
