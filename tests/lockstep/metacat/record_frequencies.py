#!/usr/bin/env python3
"""Record Metacat's answer, codelet count and final temperature for many seeds of one problem.

Reproduces the Metacat side of the answer-frequency studies: the 1,000-run study of
``wxyz -> vxyz; abcd -> ?`` (seeds 101-1100, cap 100,000: ``vbcd`` 33.6%, no answer
24.3%, ``abce`` 14.1%, ``abcd`` 13.8%) and the fidelity net's single runs.  It wraps
nothing: each seed is one plain ``init-mcat`` / ``run-mcat`` on a cleared memory, as the
study collectors do, and the answer is read from Metacat's memory afterwards.  Many seeds
share one container (about 1 s start-up each otherwise).

    python3 tests/lockstep/metacat/record_frequencies.py abc abd aabbcc 1-10 --cap 4000
    python3 tests/lockstep/metacat/record_frequencies.py wxyz vxyz abcd 101-1100 --jobs 4

Writes ``<out>/frequencies/<i>-<m>-<t>.<lo>-<hi>.cap<cap>.metacat.tsv`` (default ``--out``
``tests/lockstep/out``, git-ignored): ``#`` header lines, then one row per seed in seed
order, tab separated::

    seed  answer  codelets  temperature  clamped  since_snag

``answer`` is the answer's print name, ``*CAP*`` (no answer, ``--cap`` reached), ``*NONE*``
(no answer, Metacat gave up) or ``*ERROR*``; ``clamped`` is 0/1; ``since_snag`` is the
codelets since the last snag event (-1 if none).  A recording is byte-identical for a
given problem, seed and cap.  ``scripts/compare_frequencies.py`` tabulates and compares it
with Petacat's.  Needs Docker and the ``metacat:1.2`` image.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import wrap  # noqa: E402

COLUMNS = ["seed", "answer", "codelets", "temperature", "clamped", "since_snag"]


def driver(problem: list[str], seeds: list[int], cap: int) -> str:
    """Scheme text running ``seeds`` of ``problem`` and printing one ``FREQ`` line each."""
    i, m, t = problem
    runs = "".join(f"(one-run {s})\n" for s in seeds)
    return wrap.PRELUDE + f"""
(define (one-run run-seed)
  (tell *memory* 'clear)
  (let* ((outcome
           (guard (c (#t 'error))
             (init-mcat '{i} '{m} '{t} #f run-seed)
             (set! *break-time* {cap})
             (call/cc (lambda (k)
                        (set! suspend (lambda () (k 'suspended)))
                        (set! break (lambda () (k 'capped)))
                        (run-mcat)))))
         (answers (tell *memory* 'get-answers))
         (since-snag (guard (c (#t -1))
                       (if (exists? (tell *trace* 'get-last-event 'snag))
                           (tell *trace* 'get-elapsed-time 'snag)
                           -1))))
    (display (format "FREQ\\t~a\\t~a\\t~a\\t~a\\t~a\\t~a"
               run-seed
               (cond ((eq? outcome 'error) "*ERROR*")
                     ((not (null? answers)) (tell (car answers) 'get-answer-print-name))
                     ((eq? outcome 'capped) "*CAP*")
                     (else "*NONE*"))
               *codelet-count* *temperature* (if *temperature-clamped?* 1 0) since-snag))
    (write-char #\\newline)))
{runs}(exit 0)
"""


def parse_rows(lines: list[str]) -> dict[int, list[str]]:
    """``FREQ`` lines -> ``{seed: [answer, codelets, temperature, clamped, since_snag]}``."""
    rows: dict[int, list[str]] = {}
    for line in lines:
        f = line.rstrip("\n").split("\t")
        if f[0] == "FREQ" and len(f) == 7:
            rows[int(f[1])] = f[2:]
    return rows


def render(problem: list[str], lo: int, hi: int, cap: int, rows: dict[int, list[str]]) -> str:
    head = [
        f"# Metacat 1.2 answers: problem {' '.join(problem)}, seeds {lo}-{hi}, cap {cap}, memory cleared before each run.",
        "# Recorded by tests/lockstep/metacat/record_frequencies.py; byte-identical for a given problem, seed and cap.",
        "# Columns: " + "\t".join(COLUMNS),
    ]
    body = ["\t".join([str(s), *rows[s]]) for s in sorted(rows)]
    return "\n".join(head + body) + "\n"


def record(problem: list[str], seeds: list[int], cap: int, jobs: int) -> dict[int, list[str]]:
    """Run ``seeds`` in ``jobs`` containers (round-robin chunks); return the parsed rows."""
    chunks = [seeds[k::jobs] for k in range(jobs) if seeds[k::jobs]]

    def batch(chunk: list[int]) -> dict[int, list[str]]:
        out = wrap.run_driver(driver(problem, chunk, cap), f"freq-{'-'.join(problem)}-{chunk[0]}")
        return parse_rows(wrap.keep_lines(out, "FREQ\t"))

    rows: dict[int, list[str]] = {}
    with concurrent.futures.ThreadPoolExecutor(len(chunks)) as pool:
        for part in pool.map(batch, chunks):
            rows.update(part)
    return rows


def output_path(out: Path, problem: list[str], lo: int, hi: int, cap: int) -> Path:
    return out / "frequencies" / f"{'-'.join(problem)}.{lo}-{hi}.cap{cap}.metacat.tsv"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("problem", nargs=3, metavar=("INITIAL", "MODIFIED", "TARGET"))
    ap.add_argument("seeds", help="seed list/range, e.g. 101-1100 or 1-5,9")
    ap.add_argument("--cap", type=int, default=100000, help="codelet cap (default 100000)")
    ap.add_argument("--jobs", type=int, default=1, help="containers at once (default 1)")
    ap.add_argument("--out", type=Path, default=wrap.DEFAULT_OUT,
                    help="output root (default tests/lockstep/out)")
    args = ap.parse_args()
    for word in args.problem:
        if not re.fullmatch(r"[a-z]+", word):
            sys.exit(f"problem strings must be lowercase letters: {word!r}")
    seeds = wrap.parse_seeds(args.seeds)
    rows = record(args.problem, seeds, args.cap, max(1, args.jobs))
    path = output_path(args.out, args.problem, min(seeds), max(seeds), args.cap)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render(args.problem, min(seeds), max(seeds), args.cap, rows))
    missing = [s for s in seeds if s not in rows]
    print(f"{path}: {len(rows)}/{len(seeds)} runs" + (f"; missing {missing[:10]}" if missing else ""))
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
