#!/usr/bin/env python3
"""Record Metacat decision traces (lockstep harness, Metacat side).

Plain Python 3, standard library only.  See tests/lockstep/metacat/README.md.

    python3 tests/lockstep/metacat/record.py --problem abc abd xyz --seeds 1-10
    python3 tests/lockstep/metacat/record.py --names            # opening names
    python3 tests/lockstep/metacat/record.py --seeds 1-5 --baseline   # unpatched

Each (problem, seed) runs in its own ``metacat:1.2`` container (linux/amd64,
Chez Scheme 9.5.4, no network) on ``Metacat/build/recorder-source``, a copy of
the reconstructed ``Metacat/build/source`` with ``recorder.patch`` applied.  The
plain trace is gzipped (mtime 0, so equal traces are equal bytes) into
``<out>/<slug>/<seed>.metacat.jsonl.gz``.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import gzip
import hashlib
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
METACAT = REPO / "Metacat"
SOURCE = METACAT / "build" / "source"
RECORDER_SOURCE = METACAT / "build" / "recorder-source"
WORK = METACAT / "build" / "recorder-work"
PATCH = HERE / "recorder.patch"
IMAGE = "metacat:1.2"
DEFAULT_OUT = REPO / "tests" / "lockstep" / "traces"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def ensure_recorder_source() -> Path:
    """Copy build/source and apply recorder.patch; redo it if the patch changed."""
    if not SOURCE.is_dir():
        sys.exit(f"missing {SOURCE}; run Metacat/tools/reconstruct.py first")
    marker = RECORDER_SOURCE / ".recorder-patch.sha256"
    want = sha256(PATCH)
    if marker.exists() and marker.read_text().strip() == want \
            and marker.stat().st_mtime >= PATCH.stat().st_mtime:
        return RECORDER_SOURCE
    if RECORDER_SOURCE.exists():
        shutil.rmtree(RECORDER_SOURCE)
    shutil.copytree(SOURCE, RECORDER_SOURCE)
    with PATCH.open("rb") as handle:
        done = subprocess.run(
            ["patch", "-p1", "-s", "-d", str(RECORDER_SOURCE)],
            stdin=handle, capture_output=True, text=True)
    if done.returncode != 0:
        shutil.rmtree(RECORDER_SOURCE, ignore_errors=True)
        sys.exit(f"recorder.patch does not apply:\n{done.stdout}{done.stderr}")
    marker.write_text(want + "\n")
    return RECORDER_SOURCE


def parse_seeds(text: str) -> list[int]:
    seeds: list[int] = []
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            low, high = part.split("-", 1)
            seeds.extend(range(int(low), int(high) + 1))
        else:
            seeds.append(int(part))
    if not seeds or min(seeds) < 1 or max(seeds) > 4294967295:
        sys.exit("seeds must be in 1..4294967295")
    return seeds


def slug_of(problem: list[str]) -> str:
    return "-".join(problem)


def driver_text(problem: list[str], seed: int, cap: int, revision: str,
                snapshots: bool, audit: bool, mode: str) -> str:
    """The per-run Scheme driver (spec 5.2).  Paths are the container's."""
    i, m, t = problem
    slug = slug_of(problem)
    lines = ["(define *metacat-directory* \"/metacat/\")"]
    if audit:
        lines.append("(load \"/recorder/random-audit.ss\")")
    lines.append("(load \"/metacat/metacat-headless.ss\")")
    lines.append("(load \"/recorder/decision-trace.ss\")")
    if not snapshots:
        lines.append("(set! *tr-snapshots?* #f)")
    if mode == "names":
        lines += [
            "(tell *memory* 'clear)",
            f"(init-mcat '{i} '{m} '{t} #f {seed})",
            f"(dump-opening-names \"/x/opening-names.{slug}.json\")",
            "(exit 0)",
        ]
    else:
        lines += [
            f"(trace-open \"/x/{slug}/{seed}.metacat.jsonl\" '({i} {m} {t}) "
            f"{seed} {cap} \"{revision}\")",
            "(tell *memory* 'clear)                 ; init-mcat keeps memory (run.ss:212-213)",
            f"(init-mcat '{i} '{m} '{t} #f {seed})",
            f"(set! *break-time* {cap})",
            "(trace-run)",
            "(exit 0)",
        ]
    return "\n".join(lines) + "\n"


def baseline_driver_text(problem: list[str], seed: int, cap: int) -> str:
    """The unpatched collector-style driver (studies/support-v1a/collector.ss.in)."""
    i, m, t = problem
    return f"""(define *metacat-directory* "/metacat/")
(load "/metacat/metacat-headless.ss")
(set! report-error-and-halt
  (lambda (message object)
    (assertion-violation 'metacat-message "unrecognized object message" (cdr message))))
(reset-handler (lambda () (exit 1)))
(tell *memory* 'clear)
(let* ((outcome
         (guard (c (#t 'error))
           (init-mcat '{i} '{m} '{t} #f {seed})
           (set! *break-time* {cap})
           (call/cc (lambda (k)
                      (set! suspend (lambda () (k 'suspended)))
                      (set! break (lambda () (k 'capped)))
                      (run-mcat)))))
       (answers (tell *memory* 'get-answers)))
  (display (format "RESULT ~a ~a"
             (cond ((eq? outcome 'error) "*ERROR*")
                   ((not (null? answers)) (tell (car answers) 'get-answer-print-name))
                   ((eq? outcome 'capped) "*CAP*")
                   (else "*NONE*"))
             *codelet-count*))
  (write-char #\\newline))
(exit 0)
"""


def docker_command(source: Path, rundir: Path) -> list[str]:
    return [
        "docker", "run", "--rm", "--platform", "linux/amd64", "--network", "none",
        "-v", f"{source}:/metacat:ro",
        "-v", f"{HERE}:/recorder:ro",
        "-v", f"{rundir}:/x",
        "-w", "/metacat", "--entrypoint", "env",
        IMAGE, "-u", "DISPLAY", "scheme", "-q", "--script", "/x/driver.ss",
    ]


def run_container(source: Path, rundir: Path, timeout: int) -> tuple[int, str, float]:
    started = time.monotonic()
    done = subprocess.run(docker_command(source, rundir), capture_output=True,
                          text=True, timeout=timeout)
    return done.returncode, done.stdout + done.stderr, time.monotonic() - started


def gzip_deterministic(src: Path, dst: Path) -> int:
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_suffix(dst.suffix + ".tmp")
    with src.open("rb") as raw, tmp.open("wb") as out:
        with gzip.GzipFile(filename="", mode="wb", fileobj=out, mtime=0,
                           compresslevel=9) as zipped:
            shutil.copyfileobj(raw, zipped)
    tmp.replace(dst)
    return dst.stat().st_size


def last_record(path: Path) -> str:
    with path.open("rb") as handle:
        handle.seek(0, os.SEEK_END)
        size = handle.tell()
        handle.seek(max(0, size - 4096))
        return handle.read().decode().strip().splitlines()[-1]


def record_one(args, source: Path, revision: str, problem: list[str], seed: int) -> dict:
    slug = slug_of(problem)
    rundir = WORK / f"{slug}-{seed}-{os.getpid()}-{time.monotonic_ns()}"
    (rundir / slug).mkdir(parents=True)
    (rundir / "driver.ss").write_text(
        driver_text(problem, seed, args.cap, revision, not args.no_snapshots,
                    args.audit, "run"))
    try:
        code, output, wall = run_container(source, rundir, args.timeout)
        plain = rundir / slug / f"{seed}.metacat.jsonl"
        result = {"seed": seed, "wall": wall, "output": output, "code": code}
        if code != 0 or not plain.exists():
            result["error"] = f"container exit {code}"
            return result
        match = re.search(r"^RESULT (\S+) (\d+)$", output, re.M)
        result["state"], result["codelets"] = (match.group(1), int(match.group(2))) \
            if match else (None, None)
        result["plain_bytes"] = plain.stat().st_size
        result["end"] = last_record(plain)
        if args.keep_plain:
            keep = Path(args.out) / slug / f"{seed}.metacat.jsonl"
            keep.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(plain, keep)
        result["gz_bytes"] = gzip_deterministic(
            plain, Path(args.out) / slug / f"{seed}.metacat.jsonl.gz")
        return result
    finally:
        if not args.keep_work:
            shutil.rmtree(rundir, ignore_errors=True)


def baseline_one(args, problem: list[str], seed: int) -> dict:
    slug = slug_of(problem)
    rundir = WORK / f"base-{slug}-{seed}-{os.getpid()}-{time.monotonic_ns()}"
    rundir.mkdir(parents=True)
    (rundir / "driver.ss").write_text(baseline_driver_text(problem, seed, args.cap))
    try:
        code, output, wall = run_container(SOURCE, rundir, args.timeout)
        match = re.search(r"^RESULT (\S+) (\d+)$", output, re.M)
        return {"seed": seed, "wall": wall, "code": code,
                "state": match.group(1) if match else None,
                "codelets": int(match.group(2)) if match else None,
                "output": output}
    finally:
        shutil.rmtree(rundir, ignore_errors=True)


def dump_names(args, source: Path, problem: list[str]) -> None:
    slug = slug_of(problem)
    rundir = WORK / f"names-{slug}-{os.getpid()}"
    rundir.mkdir(parents=True)
    (rundir / "driver.ss").write_text(
        driver_text(problem, 1, args.cap, "", False, False, "names"))
    try:
        code, output, _ = run_container(source, rundir, args.timeout)
        produced = rundir / f"opening-names.{slug}.json"
        if code != 0 or not produced.exists():
            sys.exit(f"names dump failed (exit {code}):\n{output}")
        target = HERE / f"opening-names.{slug}.json"
        shutil.copyfile(produced, target)
        print(f"wrote {target}")
    finally:
        shutil.rmtree(rundir, ignore_errors=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--problem", nargs=3, metavar=("I", "M", "T"),
                        default=["abc", "abd", "xyz"])
    parser.add_argument("--seeds", default="1-10", help="e.g. 1-10 or 1,3,5-7")
    parser.add_argument("--cap", type=int, default=100000)
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--jobs", type=int, default=4)
    parser.add_argument("--no-snapshots", action="store_true")
    parser.add_argument("--timeout", type=int, default=3 * 3600,
                        help="per-container timeout in seconds")
    parser.add_argument("--names", action="store_true",
                        help="write tests/lockstep/metacat/opening-names.<slug>.json and exit")
    parser.add_argument("--baseline", action="store_true",
                        help="run the unpatched collector-style driver instead and print "
                             "answer/codelet counts (no traces written)")
    parser.add_argument("--audit", action="store_true",
                        help="debug: shadow `random` and report raw draws attributed to "
                             "no decision (the trace itself is unchanged)")
    parser.add_argument("--keep-plain", action="store_true",
                        help="also keep the uncompressed .jsonl next to the .gz")
    parser.add_argument("--keep-work", action="store_true")
    args = parser.parse_args()

    for word in args.problem:
        if not re.fullmatch(r"[a-z]+", word):
            sys.exit(f"problem strings must be lowercase letters: {word!r}")
    problem = list(args.problem)
    WORK.mkdir(parents=True, exist_ok=True)

    if args.baseline:
        seeds = parse_seeds(args.seeds)
        with concurrent.futures.ThreadPoolExecutor(args.jobs) as pool:
            for r in pool.map(lambda s: baseline_one(args, problem, s), seeds):
                print(f"seed {r['seed']}: {r['state']} {r['codelets']} "
                      f"({r['wall']:.1f}s, exit {r['code']})", flush=True)
        return

    source = ensure_recorder_source()
    if args.names:
        dump_names(args, source, problem)
        return

    revision = "metacat-bundle-manifest-sha256:" + sha256(METACAT / "manifest.json")
    seeds = parse_seeds(args.seeds)
    print(f"recording {slug_of(problem)} seeds {seeds[0]}..{seeds[-1]} ({len(seeds)}) "
          f"cap {args.cap} jobs {args.jobs} snapshots {not args.no_snapshots}", flush=True)
    failures = 0
    with concurrent.futures.ThreadPoolExecutor(args.jobs) as pool:
        futures = {pool.submit(record_one, args, source, revision, problem, s): s
                   for s in seeds}
        for future in concurrent.futures.as_completed(futures):
            r = future.result()
            if "error" in r:
                failures += 1
                print(f"seed {r['seed']}: FAILED {r['error']}\n{r['output'][-2000:]}",
                      flush=True)
                continue
            extra = ""
            if args.audit:
                extra = " | " + " ; ".join(
                    l for l in r["output"].splitlines() if l.startswith("AUDIT"))
            print(f"seed {r['seed']}: {r['state']} {r['codelets']} codelets, "
                  f"{r['wall']:.1f}s, {r['plain_bytes']/1e6:.1f} MB raw, "
                  f"{r['gz_bytes']/1e6:.2f} MB gz{extra}", flush=True)
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
