#!/usr/bin/env python3
"""Record Metacat decision traces (lockstep harness, Metacat side).

Plain Python 3, standard library only.  See tests/lockstep/metacat/README.md.

    python3 tests/lockstep/metacat/record.py --problem abc abd xyz --seeds 1-10
    python3 tests/lockstep/metacat/record.py --names            # opening names
    python3 tests/lockstep/metacat/record.py --seeds 1-5 --baseline   # no recorder patch

Each (problem, seed) runs in its own ``metacat:1.2`` container (linux/amd64,
Chez Scheme 9.5.4, no network) on a copy of the patched ``Metacat/build/source`` with
``recorder.patch`` applied (``Metacat/build/recorder-source-kf``).  "Patched" is the
reconstruction with the bundle's second patch group, the known-failure fixes
(``Metacat/patches/fixes/``).  It is the only build this module can run: every container
start goes through ``run_container``, which first calls ``require_patched`` and exits
unless ``Metacat/build/source`` verifies as the patched build (``reconstruct.py`` does the
verification).  There is no flag that picks another build.  The header's ``revision``
names the bundle manifest and always ends in ``+known-failure-fixes``.  The plain trace
is gzipped (mtime 0, so equal traces are equal bytes) into
``<out>/<slug>/<seed>.metacat.jsonl.gz``.

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


RECORDER_SOURCE = METACAT / "build" / "recorder-source-kf"
PATCHED_MARK = "fixes+"


def require_patched() -> None:
    """Exit unless ``Metacat/build/source`` verifies as the patched build (ruling 70).

    The patched build is the reconstruction with the bundle's known-failure fixes.  A missing
    tree, a tree that verifies as anything else, and a tree that verifies as nothing all
    stop here, with no container started."""
    if not SOURCE.is_dir():
        sys.exit(f"missing {SOURCE}; run Metacat/tools/reconstruct.py first, then --apply-fixes "
                 "(this harness runs only the patched Metacat)")
    state = _reconstruct().describe(SOURCE, _manifest())
    if state != "fixes":
        sys.exit(f"{SOURCE} does not verify as the patched Metacat (the reconstruction with the "
                 f"known-failure fixes; it verifies as {state!r}); this harness runs only the "
                 "patched Metacat, see Metacat/README.md, 'Optional: the known-failure fixes'")


def source_state() -> str:
    """``fixes``: ``build/source`` is the patched build.  Exits if it is not."""
    require_patched()
    return "fixes"


def ensure_recorder_source() -> Path:
    """Copy the patched ``build/source`` and apply recorder.patch; return the copy.

    The copy is redone when recorder.patch or the bundle manifest changes.  Exits unless
    ``build/source`` is the patched build."""
    require_patched()
    target = RECORDER_SOURCE
    marker = target / ".recorder-patch.sha256"
    want = f"fixes+{sha256(PATCH)}+{sha256(METACAT / 'manifest.json')}"
    if marker.exists() and marker.read_text().strip() == want \
            and marker.stat().st_mtime >= PATCH.stat().st_mtime:
        return target
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(SOURCE, target)
    with PATCH.open("rb") as handle:
        done = subprocess.run(["patch", "-p1", "-s", "-d", str(target)],
                              stdin=handle, capture_output=True, text=True)
    if done.returncode != 0:
        shutil.rmtree(target, ignore_errors=True)
        sys.exit(f"{PATCH.name} does not apply:\n{done.stdout}{done.stderr}")
    marker.write_text(want + "\n")
    return target


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


SCHEME_PATTERN = {
    "top_down": ("%top-down-codelet-pattern%", "workspace"),
    "bottom_up": ("%bottom-up-codelet-pattern%", "workspace"),
    "group": ("(against-background %very-low-urgency% %group-codelet-pattern%)", "group"),
    "bridge": ("(against-background %very-low-urgency% %bridge-codelet-pattern%)", "workspace"),
    "rule": ("(against-background %very-low-urgency% %rule-codelet-pattern%)", "rule"),
}


def parse_interventions(text: str) -> list[dict]:
    """``300:clamp-bottom_up,700:undo`` -> the list the trace header carries."""
    out = []
    for item in [x for x in text.split(",") if x]:
        at, _, op = item.partition(":")
        if op == "undo":
            out.append({"at": int(at), "op": "undo_last_clamp"})
        elif op.startswith("theme="):
            themes = []
            for item2 in op[6:].split("+"):
                typ, dim, rel = item2.split("/")
                themes.append({"type": typ, "dimension": "plato-" + dim, "relation": rel, "activation": 100})
            out.append({"at": int(at), "op": "clamp_theme_pattern", "themes": themes})
        elif op in ("self-watching-off", "self-watching-on"):
            out.append({"at": int(at), "op": "set_self_watching", "enabled": op.endswith("on")})
        elif op.startswith("clamp-") and op[6:] in SCHEME_PATTERN:
            out.append({"at": int(at), "op": "clamp_codelet_pattern", "pattern": op[6:]})
        else:
            sys.exit(f"--intervene: unknown action {item!r}")
    return out


def intervention_scheme(interventions: list[dict]) -> str:
    """The Scheme statements that schedule ``interventions`` (``decision-trace.ss``, ``trace-run``):
    the GUI's own sequence, ``gui.ss:1231-1245`` (``clamp-codelets-menu-item``) and ``:595-597``."""
    items = []
    for iv in interventions:
        if iv["op"] == "undo_last_clamp":
            body = "(tell *trace* 'undo-last-clamp)"
        elif iv["op"] == "clamp_theme_pattern":
            # the Clamp Themes dialog's result, gui.ss:905-926: one (type (dimension relation activation)...)
            # pattern per edited theme type; a relation "diff" is #f in themes.ss
            by_type: dict[str, list[str]] = {}
            for t in iv["themes"]:
                rel = "#f" if t["relation"] == "diff" else "plato-" + t["relation"]
                by_type.setdefault(t["type"], []).append(f"(list {t['dimension']} {rel} %max-theme-activation%)")
            pats = " ".join(f"(list '{typ.replace('_', '-')} {' '.join(es)})" for typ, es in by_type.items())
            body = (f"(let ((clamp-event (make-clamp-event 'manual-clamp (list {pats}) '() 'workspace))) "
                    "(tell *trace* 'undo-last-clamp) (tell *trace* 'add-event clamp-event) "
                    "(tell clamp-event 'activate))")
        elif iv["op"] == "set_self_watching":
            # the Self-watching mode check item, gui.ss:607-626 (the GUI-only widgets left out)
            body = ("(begin (set! %self-watching-enabled% #t) 'done)" if iv["enabled"] else
                    "(begin (set! %self-watching-enabled% #f) (tell *trace* 'undo-last-clamp) (delete-themes))")
        else:
            pattern, focus = SCHEME_PATTERN[iv["pattern"]]
            body = (f"(let ((clamp-event (make-clamp-event 'manual-clamp (list {pattern}) '() '{focus}))) "
                    "(tell *trace* 'undo-last-clamp) (tell *trace* 'add-event clamp-event) "
                    "(tell clamp-event 'activate))")
        items.append(f"(cons {iv['at']} (lambda () {body}))")
    return "(set! *tr-pending* (list " + " ".join(items) + "))"


def driver_text(problem: list[str], seed: int, cap: int, revision: str,
                snapshots: bool, audit: bool, mode: str, answer: str | None = None,
                episode_runs: int = 0, clear_before: tuple[int, ...] = (),
                interventions: list[dict] | None = None, self_watching: bool = True) -> str:
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
    if not self_watching:
        lines.append("(set! %self-watching-enabled% #f)")
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
            cleared = k in clear_before and k > 1
            if cleared:
                extra += ",\\\"memory_cleared\\\":true"
            if answer:
                extra += f",\\\"answer\\\":\\\"{answer}\\\""
            lines += [
                f"(if (not *tr-failed?*)",
                f"  (begin",
                f"    (set! *tr-header-extra* \"{extra}\")",
            ] + ([f"    (tell *memory* 'clear)             ; the user clears Episodic Memory before run {k}"]
                 if cleared else []) + [
                f"    (trace-open \"{prefix}/{seed}.r{k}.metacat.jsonl\" '({i} {m} {t}) "
                f"{run_seed} {cap} \"{revision}\")",
                f"    (init-mcat '{i} '{m} '{t} {a} {run_seed})   ; keeps memory (run.ss:212-213)",
                f"    (set! *break-time* {cap})",
                f"    (trace-run)))",
            ]
        lines.append("(exit 0)")
    else:
        extra = f",\\\"answer\\\":\\\"{answer}\\\"" if answer else ""
        if not self_watching:
            extra += ",\\\"self_watching\\\":false"
        if interventions:
            extra += ",\\\"interventions\\\":" + json.dumps(interventions, separators=(",", ":")).replace('"', '\\"')
        if extra:
            lines.append(f"(set! *tr-header-extra* \"{extra}\")")
        lines += [
            f"(trace-open \"{prefix}/{seed}.metacat.jsonl\" '({i} {m} {t}) "
            f"{seed} {cap} \"{revision}\")",
            "(tell *memory* 'clear)                 ; init-mcat keeps memory (run.ss:212-213)",
            f"(init-mcat '{i} '{m} '{t} {a} {seed})",
            f"(set! *break-time* {interventions[0]['at'] if interventions else cap})",
        ] + ([f"(set! *tr-cap* {cap})", intervention_scheme(interventions)] if interventions else []) + [
            "(trace-run)",
            "(exit 0)",
        ]
    return "\n".join(lines) + "\n"


def baseline_driver_text(problem: list[str], seed: int, cap: int,
                         answer: str | None = None, episode_runs: int = 0) -> str:
    """The collector-style driver, without the recorder patch, (studies/support-v1a/collector.ss.in;
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
    """Run a driver in the container on ``source``, which must be the patched build or its
    recorder copy.  Every recorder reaches Docker only through here."""
    require_patched()
    source = Path(source)
    if source.resolve() == SOURCE.resolve():
        pass
    elif source.resolve() == RECORDER_SOURCE.resolve():
        marker = RECORDER_SOURCE / ".recorder-patch.sha256"
        if not marker.exists() or not marker.read_text().startswith(PATCHED_MARK):
            sys.exit(f"{source} is not marked as a copy of the patched Metacat")
    else:
        sys.exit(f"{source} is neither the patched Metacat/build/source nor its recorder copy")
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
    clears = tuple(int(x) for x in str(args.episode_clear_before).split(",") if x)
    slug = slug_of(problem, answer)
    sub = subdir_of(answer, runs)
    rundir = WORK / f"{slug}-{seed}-{os.getpid()}-{time.monotonic_ns()}"
    (rundir / sub / slug).mkdir(parents=True)
    (rundir / "driver.ss").write_text(
        driver_text(problem, seed, args.cap, revision, not args.no_snapshots,
                    args.audit, "run", answer, runs, clears,
                    parse_interventions(args.intervene) or None, args.self_watching == "on"))
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
    parser.add_argument("--episode-clear-before", default="", metavar="K[,K...]",
                        help="with --episode-runs: also clear Episodic Memory before these runs "
                             "(1-based; a person pressing Clear Memory between two runs); "
                             "each such run's trace header carries memory_cleared")
    parser.add_argument("--self-watching", choices=["on", "off"], default="on",
                        help="Metacat's Self-watching mode (%%self-watching-enabled%%, default on); "
                             "off records a run without themes, clamps and the progress watcher's work; "
                             "the trace header carries self_watching: false and the replay runs "
                             "Petacat with self_watching_enabled_default off")
    parser.add_argument("--intervene", default="", metavar="N:OP[,N:OP...]",
                        help="a person's actions during a single run (not with --episode-runs): at "
                             "codelet N, OP is clamp-top_down, clamp-bottom_up, clamp-group, "
                             "clamp-bridge or clamp-rule (the Options menu's codelet clamps), undo "
                             "(Undo last clamp), self-watching-off or self-watching-on (the Self-watching "
                             "mode check item), or theme=TYPE/DIM/REL[+TYPE/DIM/REL...] (the Clamp Themes dialog,"
                             " e.g. theme=top_bridge/letter-category/identity); e.g. 300:clamp-bottom_up,700:undo.  The trace header "
                             "carries the list, and the replay applies the same actions")
    parser.add_argument("--answer", metavar="A",
                        help="justify mode: the answer string (lowercase letters); the "
                             "slug gets it as a fourth part, traces go under justify/")
    parser.add_argument("--names", action="store_true",
                        help="write tests/lockstep/metacat/opening-names.<slug>.json and exit")
    parser.add_argument("--baseline", action="store_true",
                        help="run the collector-style driver, without the recorder patch, on "
                             "the patched Metacat build/source, and print answer/codelet "
                             "counts (no traces written)")
    parser.add_argument("--audit", action="store_true",
                        help="debug: shadow `random` and report raw draws attributed to "
                             "no decision (the trace itself is unchanged)")
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

    source = ensure_recorder_source()
    if args.names:
        dump_names(args, source, problem)
        return

    revision = ("metacat-bundle-manifest-sha256:" + sha256(METACAT / "manifest.json")
                + "+known-failure-fixes")
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
