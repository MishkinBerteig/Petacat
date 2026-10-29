#!/usr/bin/env python3
"""Log every snag Metacat hits: the explanation and the two comment lines.

Reproduces the recorder behind ``tests/lockstep/snag_explanations_metacat.tsv`` (and the
28-problem snag sweep): inside the ``metacat:1.2`` container it wraps ``make-snag-event``
(logging the failure kind and the event's ``get-explanation``, ``trace.ss:1097-1125``)
and the comment window (logging the two lines ``process-snag`` adds,
``answers.ss:1164-1172``), then runs the problem once per seed with memory cleared before
each run.  Standard library only; needs Docker and the ``metacat:1.2`` image.

    python3 tests/lockstep/metacat/record_snags.py abc abd xyz 1-10            # cap 100000
    python3 tests/lockstep/metacat/record_snags.py abc abd xyz 1-12 --cap 6000

Lines on stdout (tab separated; ``scripts/compare_snags.py`` reads them):

    SNAG  seed  codelet-count  kind  explanation
    CMT   seed  codelet-count  eliza-line  technical-line
    END   seed  codelet-count  outcome        (outcome: the answer, capped, suspended, error)

The recorder only reads: it draws no random number, so a run's outcome is the one an
unwrapped Metacat gives for the same seed.  Output is byte-identical for equal arguments.
"""

from __future__ import annotations

import argparse
import sys

import wrap

PRELUDE = wrap.PRELUDE + r'''(define cur-seed 0)
(define orig-make-snag-event make-snag-event)
(set! make-snag-event
  (lambda args
    (let* ((ev (apply orig-make-snag-event args))
           (fr (1st (1st args))))
      (display (format "SNAG\t~a\t~a\t~a\t~a" cur-seed *codelet-count* fr (tell ev 'get-explanation)))
      (write-char #\newline)
      ev)))
(define logger-window
  (lambda msg
    (if (and (pair? (cdr msg)) (eq? (cadr msg) 'add-comment))
      (let ((e (car (caddr msg))) (t (car (cadddr msg))))
        (if (or (and (>= (string-length e) 5) (string=? (substring e 0 5) "Uh-oh"))
                (and (>= (string-length t) 3) (string=? (substring t 0 3) "Hit")))
          (begin
            (display (format "CMT\t~a\t~a\t~a\t~a" cur-seed *codelet-count* e t))
            (write-char #\newline))))
      'done)))
(define (one-run run-seed)
  (set! cur-seed run-seed)
  (tell *memory* 'clear)
  (let* ((outcome
           (guard (c (#t 'error))
             (init-mcat 'I 'M 'T #f run-seed)
             (set! *comment-window* logger-window)
             (set! *break-time* CAP)
             (call/cc (lambda (k)
                        (set! suspend (lambda () (k 'suspended)))
                        (set! break (lambda () (k 'capped)))
                        (run-mcat))))))
    (display (format "END\t~a\t~a\t~a" run-seed *codelet-count* outcome))
    (write-char #\newline)))
'''


def driver(problem: list[str], seeds: list[int], cap: int) -> str:
    """The Scheme driver text for ``problem`` (three strings) over ``seeds``."""
    i, m, t = problem
    head = PRELUDE.replace("'I 'M 'T", f"'{i} '{m} '{t}").replace("CAP", str(cap))
    return head + "".join(f"(one-run {s})\n" for s in seeds) + "(exit 0)\n"


def record(problem: list[str], seeds: list[int], cap: int = 100000) -> list[str]:
    """Run Metacat; return the SNAG/CMT/END lines."""
    out = wrap.run_driver(driver(problem, seeds, cap), "snags-" + "-".join(problem))
    return wrap.keep_lines(out, "SNAG\t", "CMT\t", "END\t")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("initial"); ap.add_argument("modified"); ap.add_argument("target")
    ap.add_argument("seeds", help="seed list such as 1-10 or 1,5,7-9")
    ap.add_argument("--cap", type=int, default=100000, help="codelet cap per run (default 100000)")
    args = ap.parse_args(argv)
    for line in record([args.initial, args.modified, args.target], wrap.parse_seeds(args.seeds), args.cap):
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
