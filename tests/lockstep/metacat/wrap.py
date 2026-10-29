"""Shared plumbing for the "wrap and log" Metacat recorders.

A wrap-and-log recorder runs the *unpatched* ``Metacat/build/source`` in the
``metacat:1.2`` container, wraps one or more Metacat procedures from a driver script
(``set!`` of a top-level definition reaches code loaded earlier, see README.md), and prints
tab-separated lines that a comparer in ``scripts/`` checks against Petacat.  The recorders
that use this module are ``record_rule_english.py``, ``record_events.py``,
``record_snags.py`` and ``record_answers.py``; ``record_comments.py`` and
``record_verbose.py`` predate it and do the same thing inline.

Nothing here is run on its own.  ``tests/lockstep/metacat/test_wrap.py`` (no Docker) covers
the parsing helpers.
"""

from __future__ import annotations

import os
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import record  # noqa: E402

REPO = record.REPO

#: Default output directory of every recorder and sweep: git-ignored, inside the repo.
DEFAULT_OUT = REPO / "tests" / "lockstep" / "out"

#: Common start of every driver: load headless Metacat, turn Metacat's halting error
#: reporting into an ordinary Scheme condition so a ``guard`` can catch it.
PRELUDE = r'''(define *metacat-directory* "/metacat/")
(load "/metacat/metacat-headless.ss")
(set! report-error-and-halt
  (lambda (message object)
    (assertion-violation 'metacat-message "unrecognized object message" (cdr message))))
(reset-handler (lambda () (exit 1)))
(define (clean s)
  (list->string (map (lambda (c) (if (memv c '(#\tab #\newline #\return)) #\space c))
                     (string->list s))))
'''


def parse_seeds(text: str) -> list[int]:
    """``"1-5,9,20-21"`` -> ``[1, 2, 3, 4, 5, 9, 20, 21]`` (order kept, duplicates dropped)."""
    seen: list[int] = []
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        lo, _, hi = part.partition("-")
        for s in range(int(lo), int(hi or lo) + 1):
            if s not in seen:
                seen.append(s)
    return seen


def slug_problem(slug: str) -> list[str]:
    """``"abc-abd-xyz"`` -> ``["abc", "abd", "xyz"]`` (a fourth part is a justify answer)."""
    return slug.split("-")[:3]


def run_driver(driver: str, tag: str, timeout: int = 7200) -> str:
    """Run ``driver`` (Scheme text) in the container, return its stdout+stderr.

    The run directory is ``Metacat/build/recorder-work/<tag>-...`` (git-ignored) and is
    removed afterwards.  Exits the process if Docker or the Metacat tree is missing.
    """
    record.source_state()
    record.WORK.mkdir(parents=True, exist_ok=True)
    rundir = record.WORK / f"{tag}-{os.getpid()}-{time.monotonic_ns()}"
    rundir.mkdir(parents=True)
    (rundir / "driver.ss").write_text(driver)
    try:
        code, out, _ = record.run_container(record.SOURCE, rundir, timeout)
    finally:
        shutil.rmtree(rundir, ignore_errors=True)
    if code != 0:
        print(f"container exit {code}: {out[-500:]}", file=sys.stderr)
    return out


def keep_lines(output: str, *prefixes: str) -> list[str]:
    """The lines of ``output`` that start with one of ``prefixes`` (tab-separated records)."""
    return [l for l in output.splitlines() if l.startswith(prefixes)]


def read_problem_list(path) -> list[list[str]]:
    """A problem-list data file (``tests/lockstep/data/*.txt``): one ``initial modified target``
    per line, ``#`` comments and blank lines skipped, duplicates dropped, order kept."""
    problems: list[list[str]] = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            parts = line.split()
            if len(parts) != 3:
                raise ValueError(f"{path}: expected three strings, got {line!r}")
            if parts not in problems:
                problems.append(parts)
    return problems
