#!/usr/bin/env python3
"""Record Metacat decision traces (lockstep harness, Metacat side).

Plain Python 3, standard library only.  See tests/lockstep/metacat/README.md.

    python3 tests/lockstep/metacat/record.py --problem abc abd xyz --seeds 1-10
    python3 tests/lockstep/metacat/record.py --names            # opening names
    python3 tests/lockstep/metacat/record.py --seeds 1-5 --baseline   # unpatched

Each (problem, seed) runs in its own ``metacat:1.2`` container (linux/amd64,
Chez Scheme 9.5.4, no network) on a copy of the reconstructed ``Metacat/build/source``
with ``recorder.patch`` applied: ``Metacat/build/recorder-source`` for the reference
reconstruction, ``Metacat/build/recorder-source-kf`` for the reconstruction with the
bundle's second patch group (``Metacat/patches/fixes/``, the known-failure fixes).  By
default the copy is of whichever of the two ``build/source`` is (``reconstruct.py``
verifies it); ``--reference`` and ``--known-failures-patch`` choose one explicitly.  The
two give byte-identical traces except on the three seeds of
``Metacat/KNOWN-FAILURES.md``.  The header's ``revision`` names the bundle manifest and,
with the fixes, ends in ``+known-failure-fixes``.  The plain trace is gzipped (mtime 0, so
equal traces are equal bytes) into ``<out>/<slug>/<seed>.metacat.jsonl.gz``.

Episodes and justify mode (task J)::

    python3 tests/lockstep/metacat/record.py --problem abc abd xyz --seeds 1-5 --episode-runs 8
    python3 tests/lockstep/metacat/record.py --problem abc abd xyz --answer wyz --seeds 1-5

``--episode-runs N`` runs N runs of the problem in one Metacat process, memory cleared
only before run 1 (``init-mcat`` keeps memory).  Run k (1-based) uses seed
``S + k - 1`` where S is the episode seed -- the convention of the study collectors
(``studies/episodic-v2/collector.ss.in``: ``(+ first_seed i)``).  Each run writes its own
trace ``<out>/episodes/<slug>/<S>.r<k>.metacat.jsonl.gz`` whose header carries
``episode_run`` k and ``episode_seed`` S (and ``seed`` = S + k - 1).  An error ends the
episode (later runs are not recorded).  ``--answer A`` is justify mode; the slug gets
the answer as a fourth part and the traces go under ``justify/`` (or
``episodes-justify/``), header field ``answer``.  The default (single-run, discovery)
layout and the existing traces are unchanged.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import gzip
import hashlib
import json
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


def _reconstruct():
    """``Metacat/tools/reconstruct.py``, which knows both patch groups."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "metacat_reconstruct", METACAT / "tools" / "reconstruct.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _manifest() -> dict:
    return json.loads((METACAT / "manifest.json").read_text())


def source_state() -> str:
    """``reference`` or ``fixes``: which reconstruction ``build/source`` is."""
    if not SOURCE.is_dir():
        sys.exit(f"missing {SOURCE}; run Metacat/tools/reconstruct.py first")
    state = _reconstruct().describe(SOURCE, _manifest())
    if state is None:
        sys.exit(f"{SOURCE} verifies neither as the reference reconstruction nor with the "
                 "known-failure fixes; see Metacat/README.md")
    return state


def ensure_recorder_source(variant: str | None = None) -> tuple[Path, str]:
    """Copy build/source as the ``variant`` reconstruction and apply recorder.patch.

    ``variant`` is ``reference``, ``fixes`` or None (whichever build/source is).  The copy
    is redone when the variant's inputs change: recorder.patch or the bundle manifest.
    Returns the copy and the variant it is."""
    state = source_state()
    variant = variant or state
    target = METACAT / "build" / ("recorder-source-kf" if variant == "fixes" else "recorder-source")
    marker = target / ".recorder-patch.sha256"
    want = f"{variant}+{sha256(PATCH)}+{sha256(METACAT / 'manifest.json')}"
    if marker.exists() and marker.read_text().strip() == want \
            and marker.stat().st_mtime >= PATCH.stat().st_mtime:
        return target, variant
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(SOURCE, target)
    if variant != state:
        rec = _reconstruct()
        (rec.apply_fixes if variant == "fixes" else rec.remove_fixes)(target, _manifest())
    with PATCH.open("rb") as handle:
        done = subprocess.run(["patch", "-p1", "-s", "-d", str(target)],
                              stdin=handle, capture_output=True, text=True)
    if done.returncode != 0:
        shutil.rmtree(target, ignore_errors=True)
        sys.exit(f"{PATCH.name} does not apply:\n{done.stdout}{done.stderr}")
    marker.write_text(want + "\n")
    return target, variant


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


def slug_of(problem: list[str], answer: str | None = None) -> str:
    return "-".join(problem + ([answer] if answer else []))


def subdir_of(args_answer, episode_runs: int) -> str:
    """Directory under ``--out`` for a recording mode ('' = the classic layout)."""
    return {(False, 0): "", (False, 1): "episodes", (True, 0): "justify",
            (True, 1): "episodes-justify"}[(bool(args_answer), 1 if episode_runs else 0)]


def trace_name(seed: int, episode_runs: int, episode_seed: int | None = None) -> str:
    """File stem of a run's trace: ``<seed>`` or ``<episode seed>.r<k>``."""
    return f"{seed}" if not episode_runs else f"{episode_seed}.r{seed - episode_seed + 1}"


def driver_text(problem: list[str], seed: int, cap: int, revision: str,
                snapshots: bool, audit: bool, mode: str, answer: str | None = None,
                episode_runs: int = 0) -> str:
    """The per-run Scheme driver (spec 5.2).  Paths are the container's."""
    i, m, t = problem
    slug = slug_of(problem, answer)
    sub = subdir_of(answer, episode_runs)
    prefix = f"/x/{sub}/{slug}" if sub else f"/x/{slug}"
    a = f"'{answer}" if answer else "#f"
    lines = ["(define *metacat-directory* \"/metacat/\")"]
    if audit:
        lines.append("(load \"/recorder/random-audit.ss\")")
    lines.append("(load \"/metacat/metacat-headless.ss\")")
    lines.append("(load \"/recorder/decision-trace.ss\")")
    if not snapshots:
        lines.append("(set! *tr-snapshots?* #f)")
    if answer:
        # Justify mode is a global the GUI sets from a 4-part problem (gui.ss:752);
        # init-mcat only reads it.
        lines.append("(set! %justify-mode% #t)")
    if mode == "names":
        lines += [
            "(tell *memory* 'clear)",
            f"(init-mcat '{i} '{m} '{t} {a} {seed})",
            f"(dump-opening-names \"/x/opening-names.{slug}.json\")",
            "(exit 0)",
        ]
    elif episode_runs:
        lines.append("(tell *memory* 'clear)                 ; once, before run 1")
        for k in range(1, episode_runs + 1):
            run_seed = seed + k - 1
            extra = f",\\\"episode_run\\\":{k},\\\"episode_seed\\\":{seed}"
            if answer:
                extra += f",\\\"answer\\\":\\\"{answer}\\\""
            lines += [
                f"(if (not *tr-failed?*)",
                f"  (begin",
                f"    (set! *tr-header-extra* \"{extra}\")",
                f"    (trace-open \"{prefix}/{seed}.r{k}.metacat.jsonl\" '({i} {m} {t}) "
                f"{run_seed} {cap} \"{revision}\")",
                f"    (init-mcat '{i} '{m} '{t} {a} {run_seed})   ; keeps memory (run.ss:212-213)",
                f"    (set! *break-time* {cap})",
                f"    (trace-run)))",
            ]
        lines.append("(exit 0)")
    else:
        if answer:
            lines.append(f"(set! *tr-header-extra* \",\\\"answer\\\":\\\"{answer}\\\"\")")
        lines += [
            f"(trace-open \"{prefix}/{seed}.metacat.jsonl\" '({i} {m} {t}) "
            f"{seed} {cap} \"{revision}\")",
            "(tell *memory* 'clear)                 ; init-mcat keeps memory (run.ss:212-213)",
            f"(init-mcat '{i} '{m} '{t} {a} {seed})",
            f"(set! *break-time* {cap})",
            "(trace-run)",
            "(exit 0)",
        ]
    return "\n".join(lines) + "\n"


def baseline_driver_text(problem: list[str], seed: int, cap: int,
                         answer: str | None = None, episode_runs: int = 0) -> str:
    """The unpatched collector-style driver (studies/support-v1a/collector.ss.in;
    with ``episode_runs`` the episodic-v2 loop: memory cleared once, seeds S+k-1)."""
    i, m, t = problem
    a = f"'{answer}" if answer else "#f"
    n = episode_runs or 1
    return f"""(define *metacat-directory* "/metacat/")
(load "/metacat/metacat-headless.ss")
(set! report-error-and-halt
  (lambda (message object)
    (assertion-violation 'metacat-message "unrecognized object message" (cdr message))))
(reset-handler (lambda () (exit 1)))
{"(set! %justify-mode% #t)" if answer else ""}
(tell *memory* 'clear)
(define (one-run run-seed)
  (let* ((before (length (tell *memory* 'get-answers)))
         (outcome
           (guard (c (#t 'error))
             (init-mcat '{i} '{m} '{t} {a} run-seed)
             (set! *break-time* {cap})
             (call/cc (lambda (k)
                        (set! suspend (lambda () (k 'suspended)))
                        (set! break (lambda () (k 'capped)))
                        (run-mcat)))))
         (answers (tell *memory* 'get-answers)))
    (display (format "RESULT ~a ~a"
               (cond ((eq? outcome 'error) "*ERROR*")
                     ((> (length answers) before) (tell (car answers) 'get-answer-print-name))
                     ((eq? outcome 'capped) "*CAP*")
                     (else "*NONE*"))
               *codelet-count*))
    (write-char #\\newline)
    outcome))
(let loop ((k 0))
  (if (< k {n})
      (if (not (eq? (one-run (+ {seed} k)) 'error)) (loop (+ k 1)))))
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
    answer, runs = args.answer, args.episode_runs
    slug = slug_of(problem, answer)
    sub = subdir_of(answer, runs)
    rundir = WORK / f"{slug}-{seed}-{os.getpid()}-{time.monotonic_ns()}"
    (rundir / sub / slug).mkdir(parents=True)
    (rundir / "driver.ss").write_text(
        driver_text(problem, seed, args.cap, revision, not args.no_snapshots,
                    args.audit, "run", answer, runs))
    try:
        code, output, wall = run_container(source, rundir, args.timeout)
        stems = [f"{seed}.r{k}" for k in range(1, runs + 1)] if runs else [f"{seed}"]
        plains = [rundir / sub / slug / f"{stem}.metacat.jsonl" for stem in stems]
        result = {"seed": seed, "wall": wall, "output": output, "code": code}
        if code != 0 or not plains[0].exists():
            result["error"] = f"container exit {code}"
            return result
        matches = re.findall(r"^RESULT (\S+) (\d+)$", output, re.M)
        result["state"], result["codelets"] = (matches[0][0], int(matches[0][1])) \
            if matches else (None, None)
        result["results"] = [(st, int(n)) for st, n in matches]
        done = [p for p in plains if p.exists()]
        result["plain_bytes"] = sum(p.stat().st_size for p in done)
        result["end"] = last_record(done[-1])
        out = Path(args.out) / sub / slug
        result["gz_bytes"] = 0
        for p in done:
            if args.keep_plain:
                out.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(p, out / p.name)
            result["gz_bytes"] += gzip_deterministic(p, out / (p.name + ".gz"))
        result["files"] = [p.name + ".gz" for p in done]
        return result
    finally:
        if not args.keep_work:
            shutil.rmtree(rundir, ignore_errors=True)


def baseline_one(args, problem: list[str], seed: int) -> dict:
    slug = slug_of(problem, args.answer)
    rundir = WORK / f"base-{slug}-{seed}-{os.getpid()}-{time.monotonic_ns()}"
    rundir.mkdir(parents=True)
    (rundir / "driver.ss").write_text(
        baseline_driver_text(problem, seed, args.cap, args.answer, args.episode_runs))
    try:
        code, output, wall = run_container(SOURCE, rundir, args.timeout)
        matches = re.findall(r"^RESULT (\S+) (\d+)$", output, re.M)
        return {"seed": seed, "wall": wall, "code": code,
                "state": matches[0][0] if matches else None,
                "codelets": int(matches[0][1]) if matches else None,
                "results": [(st, int(n)) for st, n in matches],
                "output": output}
    finally:
        shutil.rmtree(rundir, ignore_errors=True)


def dump_names(args, source: Path, problem: list[str]) -> None:
    slug = slug_of(problem, args.answer)
    rundir = WORK / f"names-{slug}-{os.getpid()}"
    rundir.mkdir(parents=True)
    (rundir / "driver.ss").write_text(
        driver_text(problem, 1, args.cap, "", False, False, "names", args.answer))
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
    parser.add_argument("--episode-runs", type=int, default=0, metavar="N",
                        help="record an episode: N runs of the problem in one process, "
                             "memory cleared only before run 1; run k uses seed S+k-1 "
                             "(S = each value of --seeds); traces <S>.r<k> under episodes/")
    parser.add_argument("--answer", metavar="A",
                        help="justify mode: the answer string (lowercase letters); the "
                             "slug gets it as a fourth part, traces go under justify/")
    parser.add_argument("--names", action="store_true",
                        help="write tests/lockstep/metacat/opening-names.<slug>.json and exit")
    parser.add_argument("--baseline", action="store_true",
                        help="run the unpatched collector-style driver instead and print "
                             "answer/codelet counts (no traces written)")
    parser.add_argument("--audit", action="store_true",
                        help="debug: shadow `random` and report raw draws attributed to "
                             "no decision (the trace itself is unchanged)")
    variant = parser.add_mutually_exclusive_group()
    variant.add_argument("--known-failures-patch", action="store_true",
                         help="record Metacat with the bundle's second patch group (the "
                              "known-failure fixes), whichever build/source is")
    variant.add_argument("--reference", action="store_true",
                         help="record the reference reconstruction (without the fixes), "
                              "whichever build/source is")
    parser.add_argument("--keep-plain", action="store_true",
                        help="also keep the uncompressed .jsonl next to the .gz")
    parser.add_argument("--keep-work", action="store_true")
    args = parser.parse_args()

    for word in args.problem + ([args.answer] if args.answer else []):
        if not re.fullmatch(r"[a-z]+", word):
            sys.exit(f"problem strings must be lowercase letters: {word!r}")
    problem = list(args.problem)
    WORK.mkdir(parents=True, exist_ok=True)

    if args.baseline:
        seeds = parse_seeds(args.seeds)
        with concurrent.futures.ThreadPoolExecutor(args.jobs) as pool:
            for r in pool.map(lambda s: baseline_one(args, problem, s), seeds):
                print(f"seed {r['seed']}: {r['state']} {r['codelets']} "
                      f"({r['wall']:.1f}s, exit {r['code']})"
                      + (" | " + " ".join(f"{st}/{n}" for st, n in r["results"])
                         if args.episode_runs else ""), flush=True)
        return

    source, variant = ensure_recorder_source(
        "fixes" if args.known_failures_patch else "reference" if args.reference else None)
    if args.names:
        dump_names(args, source, problem)
        return

    revision = "metacat-bundle-manifest-sha256:" + sha256(METACAT / "manifest.json")
    if variant == "fixes":
        revision += "+known-failure-fixes"
    seeds = parse_seeds(args.seeds)
    print(f"recording {slug_of(problem, args.answer)} seeds {seeds[0]}..{seeds[-1]} ({len(seeds)}) "
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
            if args.episode_runs:
                print(f"episode {r['seed']}: " + " ".join(f"{st}/{n}" for st, n in r["results"])
                      + f" ({len(r['files'])} runs, {r['wall']:.1f}s, "
                      f"{r['plain_bytes']/1e6:.1f} MB raw, {r['gz_bytes']/1e6:.2f} MB gz)",
                      flush=True)
                continue
            print(f"seed {r['seed']}: {r['state']} {r['codelets']} codelets, "
                  f"{r['wall']:.1f}s, {r['plain_bytes']/1e6:.1f} MB raw, "
                  f"{r['gz_bytes']/1e6:.2f} MB gz{extra}", flush=True)
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
