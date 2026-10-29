#!/usr/bin/env python3
"""Log how Metacat explains and compares the answers an episode leaves in memory.

Reproduces the Metacat side of the episode answer check (the "answer explanation and
comparison" of the 25-episode snag check and of the fidelity net's widened episodes).  One
container runs one episode: memory is cleared once, then the problem runs once per seed
(seeds ``LO..HI``, memory carried; the episode convention is seed ``S + k - 1`` for run
``k``).  Afterwards, for every answer in ``*memory*`` it logs the snag explanation the
answer carries (``get-snag-explanation``), the two-voice explanation the Memory window's
"explain" button writes (``explain``) and, for every ordered pair of answers, the
comparison text (``get-answer-comparison-text``).  Standard library only; needs Docker and
the ``metacat:1.2`` image.

    python3 tests/lockstep/metacat/record_answers.py abc abd xyz 1-8
    python3 tests/lockstep/metacat/record_answers.py abc abd ijkk 3-10 --cap 5000

Lines on stdout (tab separated; ``scripts/compare_episode_answers.py`` reads them), in
the order Metacat holds the answers (most recent first, as ``get-answers`` returns):

    END   seed  codelet-count  outcome
    ANS   key   snag-explanation               key = answer|top rule phrases joined by /
    EXPL  key   eliza-text  technical-text
    CMP   key-a key-b  comparison-text
"""

from __future__ import annotations

import argparse
import sys

import wrap

PRELUDE = wrap.PRELUDE + r'''(define cur-seed 0)
(define (join-with sep l)
  (if (null? l) "" (apply string-append (car l) (map (lambda (x) (string-append sep x)) (cdr l)))))
(define last-comment #f)
(define capture-window
  (lambda msg
    (if (and (pair? (cdr msg)) (eq? (cadr msg) 'add-comment))
      (set! last-comment (list (caddr msg) (cadddr msg))))
    'done))
(define (key a) (format "~a|~a" (tell a 'get-answer-print-name) (join-with "/" (tell a 'get-top-rule-phrases))))
(define (dump)
  (set! *comment-window* capture-window)
  (let ((answers (tell *memory* 'get-answers)))
    (for* each a in answers do
      (display (format "ANS\t~a\t~a" (key a) (get-snag-explanation a))) (write-char #\newline)
      (explain a)
      (display (format "EXPL\t~a\t~a\t~a" (key a) (apply string-append (car last-comment)) (apply string-append (cadr last-comment))))
      (write-char #\newline))
    (for* each a in answers do
      (for* each b in answers do
        (if* (not (eq? a b))
          (begin
          (display (format "CMP\t~a\t~a\t~a" (key a) (key b) (get-answer-comparison-text a b)))
          (write-char #\newline)))))))
(define (one-run run-seed)
  (set! cur-seed run-seed)
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


def driver(problem: list[str], seeds: list[int], cap: int) -> str:
    """The Scheme driver text: one episode over ``seeds`` with memory carried."""
    i, m, t = problem
    head = PRELUDE.replace("'I 'M 'T", f"'{i} '{m} '{t}").replace("CAP", str(cap))
    return (head + "(tell *memory* 'clear)\n" + "".join(f"(one-run {s})\n" for s in seeds)
            + "(dump)\n(exit 0)\n")


def record(problem: list[str], seeds: list[int], cap: int = 100000) -> list[str]:
    """Run Metacat; return the END/ANS/EXPL/CMP lines."""
    out = wrap.run_driver(driver(problem, seeds, cap), "answers-" + "-".join(problem))
    return wrap.keep_lines(out, "ANS\t", "EXPL\t", "CMP\t", "END\t")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("initial"); ap.add_argument("modified"); ap.add_argument("target")
    ap.add_argument("seeds", help="the episode's run seeds, LO-HI (memory carried across them)")
    ap.add_argument("--cap", type=int, default=100000, help="codelet cap per run (default 100000)")
    args = ap.parse_args(argv)
    for line in record([args.initial, args.modified, args.target], wrap.parse_seeds(args.seeds), args.cap):
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
