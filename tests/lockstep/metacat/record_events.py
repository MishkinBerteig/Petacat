#!/usr/bin/env python3
"""Log Metacat 1.2's Temporal Trace events: their print-names and headers.

Reproduces the data of ``tests/lockstep/event_names_metacat.tsv``.  After each run the
recorder walks ``*trace*`` of the unpatched ``metacat:1.2`` container, asks every event for
its ``'print-name`` (``trace.ss``) and for the header its ``'display-workspace`` hands to
``draw-event-header`` (captured by replacing ``*workspace-window*``), and prints

    EV<TAB>seed<TAB>event-number<TAB>type<TAB>codelet<TAB>temperature<TAB>print-name<TAB>header
    END<TAB>seed<TAB>codelet-count<TAB>outcome

Metacat's event types are its own (``concept-activation``, ``group``, ``concept-mapping``,
``rule``, ``answer``, ``snag``, ``clamp``); ``scripts/compare_events.py`` maps them to
Petacat's.  Memory is cleared before every run.

    python3 tests/lockstep/metacat/record_events.py abc abd xyz 1-10
    python3 tests/lockstep/metacat/record_events.py abc abd mrrjjj 1-5 --answer mrrkkk   # justify mode

Prints on stdout; one container per call, 1-2 s per run of 1,000-3,000 codelets.
Needs Docker and the ``metacat:1.2`` image.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import wrap  # noqa: E402

DRIVER_BODY = r'''(define last-header #f)
(define capture-ws
  (lambda msg
    (if (and (pair? (cdr msg)) (eq? (cadr msg) 'draw-event-header))
      (set! last-header (caddr msg)))
    'done))
(define (header-of e)
  (set! last-header "?")
  (guard (c (#t (set! last-header "ERR")))
    (tell e 'display-workspace))
  last-header)
(define (dump-events seed)
  (let ((saved *workspace-window*))
    (set! *workspace-window* capture-ws)
    (for* each e in (reverse (tell *trace* 'get-all-events)) do
      (let ((h (header-of e)))
        (display (format "EV\t~a\t~a\t~a\t~a\t~a\t~a\t~a"
          seed (tell e 'get-event-number) (tell e 'get-type) (tell e 'get-time)
          (tell e 'get-temperature) (clean (tell e 'print-name)) (clean h)))
        (write-char #\newline)))
    (set! *workspace-window* saved)))
(define (one-run run-seed)
  (tell *memory* 'clear)
  (let* ((outcome
           (guard (c (#t 'error))
             (init-mcat 'I 'M 'T ANS run-seed)
             (set! *break-time* CAP)
             (call/cc (lambda (k)
                        (set! suspend (lambda () (k 'suspended)))
                        (set! break (lambda () (k 'capped)))
                        (run-mcat))))))
    (display (format "END\t~a\t~a\t~a" run-seed *codelet-count* outcome))
    (write-char #\newline)
    (dump-events run-seed)))
'''


def driver_text(problem: list[str], seeds: list[int], answer: str | None, cap: int) -> str:
    body = (DRIVER_BODY.replace("'I 'M 'T ANS", "'{} '{} '{} {}".format(*problem, f"'{answer}" if answer else "#f"))
            .replace("CAP", str(cap)))
    justify = "(set! %justify-mode% #t)\n" if answer else ""
    return wrap.PRELUDE + justify + body + "".join(f"(one-run {s})\n" for s in seeds) + "(exit 0)\n"


def record(problem: list[str], seeds: list[int], answer: str | None = None,
           cap: int = 100000) -> list[str]:
    """The EV and END lines of one container run."""
    out = wrap.run_driver(driver_text(problem, seeds, answer, cap),
                          "events-" + "-".join(problem + ([answer] if answer else [])))
    return wrap.keep_lines(out, "EV\t", "END\t")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("initial")
    ap.add_argument("modified")
    ap.add_argument("target")
    ap.add_argument("seeds", help="seed or list such as 1-5,9")
    ap.add_argument("--answer", help="justify mode: the answer to justify")
    ap.add_argument("--cap", type=int, default=100000)
    a = ap.parse_args()
    for line in record([a.initial, a.modified, a.target], wrap.parse_seeds(a.seeds), a.answer, a.cap):
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
