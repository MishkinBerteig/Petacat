#!/usr/bin/env python3
"""Versioned, resumable collection. Run only on the designated study machine."""

from __future__ import annotations

import argparse
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import datetime, timezone
import fcntl
import hashlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SCOPES = ["server/engine", "seed_data", "Metacat", "studies/support-v1", "pyproject.toml"]


def now():
    return datetime.now(timezone.utc).isoformat()


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text())


def write_json(path, value):
    path = Path(path)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    temp.replace(path)


def capture(command, **kwargs):
    return subprocess.run(command, check=True, text=True, capture_output=True,
                          **kwargs).stdout.strip()


def source_snapshot():
    dirty = capture(["git", "status", "--porcelain", "--untracked-files=all", "--", *SCOPES], cwd=ROOT)
    if dirty:
        raise ValueError("Study inputs must be committed and clean:\n" + dirty)
    names = capture(["git", "ls-files", "-z", "--", *SCOPES], cwd=ROOT).split("\0")
    files = {name: sha(ROOT / name) for name in names if name}
    if "studies/support-v1/collect.py" not in files:
        raise ValueError("Commit the study tools before preparing a study")
    return {"git_commit": capture(["git", "rev-parse", "HEAD"], cwd=ROOT),
            "git_tree": capture(["git", "rev-parse", "HEAD^{tree}"], cwd=ROOT),
            "files": files}


def python_runtime():
    return {"version": platform.python_version(), "implementation": platform.python_implementation(),
            "system": platform.system(), "release": platform.release(),
            "architecture": platform.machine(),
            "packages": dict(sorted((d.metadata["Name"], d.version)
                                    for d in importlib.metadata.distributions()))}


def validate_protocol(p):
    if p["backend"] != "numpy" or p["max_codelets"] <= 0 or p["chunk_size"] <= 0:
        raise ValueError("Invalid backend, cap, or chunk size")
    names = [x["name"] for x in p["problems"]]
    if len(set(names)) != len(names):
        raise ValueError("Duplicate problem")
    for x in p["problems"]:
        if not re.fullmatch(r"[a-zA-Z0-9.-]+", x["name"]):
            raise ValueError("Unsafe problem name")
        if len(x["strings"]) != 3 or not all(re.fullmatch("[a-z]+", s) for s in x["strings"]):
            raise ValueError("Inputs must be three lowercase letter strings")
    ranges = []
    for phase in p["phases"] + p["pilot_phases"]:
        if not re.fullmatch(r"[a-z-]+", phase["name"]) or phase["engine"] not in ("metacat", "petacat"):
            raise ValueError("Invalid phase")
        n = phase["runs_per_problem"]
        if not 0 < n <= p["seed_stride"]:
            raise ValueError("Invalid run count")
        for i in range(len(names)):
            start = phase["seed_base"] + i * p["seed_stride"]
            if not 0 < start <= start + n - 1 < 2**32:
                raise ValueError("Seed outside Chez range")
            ranges.append((start, start + n))
    ranges.sort()
    if any(a[1] > b[0] for a, b in zip(ranges, ranges[1:])):
        raise ValueError("Overlapping seed blocks")


def tasks_for(p, phase):
    # Interleave inputs so progress is not dominated by the first input.
    for offset in range(0, phase["runs_per_problem"], p["chunk_size"]):
        for i, problem in enumerate(p["problems"]):
            yield {"phase": phase["name"], "engine": phase["engine"],
                   "problem": problem["name"], "strings": problem["strings"],
                   "offset": offset, "count": min(p["chunk_size"], phase["runs_per_problem"] - offset),
                   "first_seed": phase["seed_base"] + i * p["seed_stride"] + offset,
                   "cap": p["max_codelets"], "backend": p["backend"]}


def chunk_dir(out, task):
    return out / "chunks" / task["phase"] / task["problem"] / f"{task['offset']:06d}"


def validate_rows(rows, task):
    if len(rows) != task["count"]:
        raise ValueError(f"Expected {task['count']} rows, got {len(rows)}")
    for i, row in enumerate(rows):
        expected = {"phase": task["phase"], "engine": task["engine"], "problem": task["problem"],
                    "index": task["offset"] + i, "seed": task["first_seed"] + i,
                    "max_codelets": task["cap"]}
        if any(row.get(k) != v for k, v in expected.items()):
            raise ValueError("Run identity mismatch")
        if not isinstance(row.get("codelets"), int) or not 0 <= row["codelets"] <= task["cap"]:
            raise ValueError("Invalid codelet count")
        state = row.get("state", "")
        if not re.fullmatch(r"[a-z]+|\*NONE\*|\*CAP\*", state):
            raise ValueError("Invalid outcome")
        if state == "*CAP*" and row["codelets"] != task["cap"]:
            raise ValueError("Cap state without reaching cap")
        if not math.isfinite(row["elapsed_seconds"]) or row["elapsed_seconds"] < 0:
            raise ValueError("Invalid run time")


def load_completed(directory, task):
    receipt = directory / "complete.json"
    if not receipt.exists():
        return None
    info = read_json(receipt)
    if info["task"] != task or not re.fullmatch(r"attempt-\d+", info["attempt"]):
        raise ValueError("Chunk receipt does not match assignment")
    attempt = directory / info["attempt"]
    if sha(attempt / "runs.jsonl") != info["sha256"]:
        raise ValueError("Completed data checksum mismatch")
    for name, expected in info["artifacts"].items():
        if Path(name).name != name or sha(attempt / name) != expected:
            raise ValueError("Chunk artifact checksum mismatch")
    rows = [json.loads(line) for line in (attempt / "runs.jsonl").read_text().splitlines()]
    validate_rows(rows, task)
    return rows


def docker_base(local):
    return [local["docker"], "run", "--rm", "--platform", "linux/amd64", "--network", "none",
            "--cpus", "1", "--memory", "2g"]


def runtime_snapshot(local):
    base = docker_base(local)
    runtime = capture([*base, "-v", f"{HERE}:/study:ro", "--entrypoint", "env",
                       local["image"], "-u", "DISPLAY", "scheme", "-q", "--script", "/study/runtime.ss"])
    binaries = capture([*base, "--entrypoint", "sh", local["image"], "-c",
                        "sha256sum /usr/local/bin/scheme /usr/local/lib/csv9.5.4/a6le/*.boot"])
    packages = capture([*base, "--entrypoint", "dpkg-query", local["image"], "-W",
                        "-f=${Package}=${Version}\n"])
    return {"scheme": runtime, "runtime_file_hashes": binaries.splitlines(),
            "debian_packages": packages.splitlines(), "platform": "linux/amd64",
            "docker_version": capture([local["docker"], "version", "--format", "{{.Server.Version}}"])}


def verify_reconstruction(local):
    subprocess.run([sys.executable, str(ROOT / "Metacat/tools/reconstruct.py"),
                    "--verify", local["source"]], check=True)


def prepare(args):
    out = args.out.resolve()
    if out.exists():
        raise ValueError("Refusing to replace an existing study directory")
    p = read_json(HERE / "protocol.json")
    validate_protocol(p)
    source = source_snapshot()
    docker = shutil.which("docker")
    if not docker:
        raise ValueError("Docker must be on PATH")
    image = capture([docker, "image", "inspect", args.image, "--format", "{{.Id}}"])
    local = {"docker": docker, "image": image, "source": str((ROOT / "Metacat/build/source").resolve()),
             "python": sys.executable}
    verify_reconstruction(local)
    runtime = runtime_snapshot(local)
    smoke = capture([*docker_base(local), "-v", f"{local['source']}:/metacat:ro",
                     "-v", f"{ROOT / 'Metacat/tests'}:/tests:ro", "-w", "/metacat",
                     "--entrypoint", "env", image, "-u", "DISPLAY", "scheme", "-q",
                     "--script", "/tests/smoke.ss"])
    if "PASS headless smoke and targeted method checks" not in smoke:
        raise ValueError("Reference smoke test did not pass")
    out.mkdir(parents=True)
    shutil.copyfile(HERE / "protocol.json", out / "protocol.json")
    write_json(out / "local.json", local)
    write_json(out / "manifest.json", {"schema_version": 1, "study_id": p["study_id"],
               "prepared_utc": now(), "pilot": args.pilot, "source": source,
               "protocol_sha256": sha(out / "protocol.json"), "python": python_runtime(),
               "reference_runtime": runtime, "smoke_output": smoke.splitlines(),
               "numeric_environment": {"PETACAT_NUMERIC_BACKEND": "numpy",
                 "OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1", "VECLIB_MAXIMUM_THREADS": "1",
                 "PYTHONHASHSEED": "0"},
               "source_note": "Reference reconstructed only from the committed patch bundle."})
    print(f"Prepared {'pilot' if args.pilot else 'main'} study: {out}", flush=True)


def verify_study(out, runtime=True):
    manifest = read_json(out / "manifest.json")
    p = read_json(out / "protocol.json")
    validate_protocol(p)
    if sha(out / "protocol.json") != manifest["protocol_sha256"]:
        raise ValueError("Protocol changed after preparation")
    if source_snapshot() != manifest["source"]:
        raise ValueError("Checkout changed after preparation; use the original commit")
    if python_runtime() != manifest["python"]:
        raise ValueError("Python environment changed after preparation")
    local = read_json(out / "local.json")
    verify_reconstruction(local)
    if runtime and runtime_snapshot(local) != manifest["reference_runtime"]:
        raise ValueError("Reference runtime changed after preparation")
    return manifest, p, local


def row_identity(task, i):
    return {"phase": task["phase"], "engine": task["engine"], "problem": task["problem"],
            "index": task["offset"] + i, "seed": task["first_seed"] + i,
            "max_codelets": task["cap"]}


def scheme_script(task):
    initial, modified, target = task["strings"]
    return f'''(define *metacat-directory* "/metacat/")
(load "/metacat/metacat-headless.ss")
(set! report-error-and-halt
  (lambda (message object)
    (printf "STUDY ERROR bad message: ~a~%" (cdr message)) (exit 1)))
(reset-handler (lambda () (exit 1)))
(define output (open-output-file "/out/raw.tsv" 'error))
(let loop ((i 0))
  (when (< i {task['count']})
    (let ((started (real-time)) (seed (+ {task['first_seed']} i)))
      (tell *memory* 'clear)
      (init-mcat '{initial} '{modified} '{target} #f seed)
      (set! *break-time* {task['cap']})
      (let* ((outcome (call/cc (lambda (k)
                         (set! suspend (lambda () (k 'suspended)))
                         (set! break (lambda () (k 'capped)))
                         (run-mcat))))
             (answers (tell *memory* 'get-answers))
             (state (cond ((not (null? answers))
                            (tell (car answers) 'get-answer-print-name))
                          ((eq? outcome 'capped) "*CAP*")
                          (else "*NONE*"))))
        (display (format "~a\\t~a\\t~a\\t~a\\t~a\\t~a"
                   i seed state *codelet-count* (- (real-time) started) outcome) output)
        (write-char #\\newline output)
        (flush-output-port output)))
    (loop (+ i 1))))
(close-output-port output)
(exit 0)
'''


def petacat_worker(task_path, output):
    task = read_json(task_path)
    os.environ["PETACAT_NUMERIC_BACKEND"] = task["backend"]
    sys.path.insert(0, str(ROOT))
    from server.engine.metadata import MetadataProvider
    from server.engine.runner import EngineRunner, STATUS_ANSWER_FOUND, STATUS_GAVE_UP, STATUS_HALTED
    meta = MetadataProvider.from_seed_data(str(ROOT / "seed_data"))
    with output.open("x") as stream:
        for i in range(task["count"]):
            started = time.perf_counter()
            runner = EngineRunner(meta)
            runner.init_mcat(*task["strings"], seed=task["first_seed"] + i)
            runner.run_mcat(max_steps=task["cap"])
            count = runner.ctx.codelet_count
            if runner.status == STATUS_ANSWER_FOUND:
                if runner.ctx.workspace.answer_string is None:
                    raise ValueError("Answer status without an answer")
                state = runner.ctx.workspace.answer_string.text
            elif runner.status == STATUS_HALTED and count == task["cap"]:
                state = "*CAP*"
            elif runner.status == STATUS_GAVE_UP:
                state = "*NONE*"
            else:
                raise ValueError(f"Unexpected terminal status {runner.status} at {count}")
            row = {**row_identity(task, i), "state": state, "codelets": count,
                   "termination": runner.status, "elapsed_seconds": time.perf_counter() - started}
            stream.write(json.dumps(row, sort_keys=True) + "\n")
            stream.flush()


def execute_task(out, task, local, manifest, timeout):
    directory = chunk_dir(out, task)
    directory.mkdir(parents=True, exist_ok=True)
    previous = load_completed(directory, task)
    if previous is not None:
        return len(previous)
    number = 1 + max([int(p.name.split("-")[1]) for p in directory.glob("attempt-*")], default=0)
    attempt = directory / f"attempt-{number:03d}"
    attempt.mkdir()
    write_json(attempt / "task.json", task)
    started = time.monotonic()
    metadata = {"started_utc": now(), "task": task, "attempt": attempt.name}
    write_json(attempt / "attempt.json", metadata)
    env = dict(os.environ, **manifest["numeric_environment"])
    command = None
    container_name = None
    try:
        if task["engine"] == "metacat":
            (attempt / "collector.ss").write_text(scheme_script(task))
            container_name = "support-" + hashlib.sha256(str(attempt).encode()).hexdigest()[:20]
            command = [*docker_base(local), "--name", container_name,
                       "-v", f"{local['source']}:/metacat:ro", "-v", f"{attempt}:/out",
                       "-w", "/metacat", "--entrypoint", "env", local["image"], "-u", "DISPLAY",
                       "scheme", "-q", "--script", "/out/collector.ss"]
        else:
            command = [sys.executable, str(HERE / "collect.py"), "worker", "--task",
                       str(attempt / "task.json"), "--output", str(attempt / "runs.jsonl")]
        with (attempt / "stdout.log").open("w") as stdout, (attempt / "stderr.log").open("w") as stderr:
            subprocess.run(command, stdout=stdout, stderr=stderr, env=env, check=True, timeout=timeout)
        if task["engine"] == "metacat":
            rows = []
            for line in (attempt / "raw.tsv").read_text().splitlines():
                index, seed, state, count, elapsed, termination = line.split("\t")
                i = len(rows)
                if int(index) != i or int(seed) != task["first_seed"] + i:
                    raise ValueError("Unexpected raw Scheme run identity")
                rows.append({**row_identity(task, i), "state": state, "codelets": int(count),
                             "elapsed_seconds": int(elapsed) / 1000, "termination": termination})
            validate_rows(rows, task)
            with (attempt / "runs.jsonl").open("x") as stream:
                for row in rows:
                    stream.write(json.dumps(row, sort_keys=True) + "\n")
        rows = [json.loads(line) for line in (attempt / "runs.jsonl").read_text().splitlines()]
        validate_rows(rows, task)
        metadata.update({"finished_utc": now(), "wall_seconds": time.monotonic() - started,
                         "exit_status": 0, "runs": len(rows)})
        write_json(attempt / "attempt.json", metadata)
        artifacts = {p.name: sha(p) for p in attempt.iterdir() if p.is_file()}
        write_json(directory / "complete.json", {**metadata, "sha256": sha(attempt / "runs.jsonl"),
                                                  "artifacts": artifacts})
        return len(rows)
    except Exception as exc:
        # A timed-out Docker client need not stop its container. Only stop ours.
        if container_name:
            subprocess.run([local["docker"], "stop", "-t", "5", container_name], capture_output=True)
        metadata.update({"finished_utc": now(), "wall_seconds": time.monotonic() - started,
                         "error_type": type(exc).__name__, "exit_status": getattr(exc, "returncode", None)})
        write_json(attempt / "attempt.json", metadata)
        raise RuntimeError(f"Failed {task['phase']}/{task['problem']}/{task['offset']}; see attempt logs") from exc


def run_study(args):
    out = args.out.resolve()
    with (out / "coordinator.lock").open("a+") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ValueError("A coordinator already owns this study") from exc
        manifest, p, local = verify_study(out)
        if (out / "COMPLETE.json").exists():
            print("Study already complete; analysis can verify all chunks.")
            return
        phases = p["pilot_phases"] if manifest["pilot"] else p["phases"]
        total = sum(x["runs_per_problem"] * len(p["problems"]) for x in phases)
        progress = {"started_utc": now(), "total_runs": total, "state": "running", "completed_runs": 0}
        inventory = {}
        try:
            for phase in phases:
                assignments = list(tasks_for(p, phase))
                todo = []
                for task in assignments:
                    if load_completed(chunk_dir(out, task), task) is None:
                        todo.append(task)
                    else:
                        progress["completed_runs"] += task["count"]
                progress["phase"] = phase["name"]
                pending_tasks = iter(todo)
                with ThreadPoolExecutor(max_workers=p["workers"]) as pool:
                    pending = {}
                    while True:
                        stopping = (out / "STOP").exists()
                        while not stopping and len(pending) < p["workers"]:
                            task = next(pending_tasks, None)
                            if task is None:
                                break
                            future = pool.submit(execute_task, out, task, local, manifest,
                                                 p["chunk_timeout_seconds"])
                            pending[future] = task
                        progress.update({"heartbeat_utc": now(), "active_chunks": len(pending),
                                         "state": "stopping" if stopping else "running"})
                        write_json(out / "progress.json", progress)
                        if not pending:
                            if stopping:
                                progress["state"] = "stopped"
                                write_json(out / "progress.json", progress)
                                return
                            break
                        done, _ = wait(pending, timeout=10, return_when=FIRST_COMPLETED)
                        for future in done:
                            task = pending.pop(future)
                            progress["completed_runs"] += future.result()
                            print(f"{now()} {phase['name']} {task['problem']} {task['offset']} "
                                  f"{progress['completed_runs']}/{total}", flush=True)
                for task in assignments:
                    directory = chunk_dir(out, task)
                    if load_completed(directory, task) is None:
                        raise ValueError("Phase ended without all assigned runs")
                    inventory[str(directory.relative_to(out) / "complete.json")] = sha(directory / "complete.json")
                # Detect accidental edits while jobs ran, before opening the next phase.
                verify_study(out, runtime=False)
            write_json(out / "COMPLETE.json", {"completed_utc": now(), "total_runs": total,
                       "manifest_sha256": sha(out / "manifest.json"), "receipts": inventory})
            progress.update({"state": "complete", "heartbeat_utc": now(), "active_chunks": 0})
            write_json(out / "progress.json", progress)
        except Exception as exc:
            progress.update({"state": "failed", "heartbeat_utc": now(), "error": str(exc)})
            write_json(out / "progress.json", progress)
            raise


def status(out):
    manifest = read_json(out / "manifest.json")
    p = read_json(out / "protocol.json")
    phases = p["pilot_phases"] if manifest["pilot"] else p["phases"]
    counts = {}
    for phase in phases:
        counts[phase["name"]] = sum(task["count"] for task in tasks_for(p, phase)
                                   if (chunk_dir(out, task) / "complete.json").exists())
    print(json.dumps({"receipted_runs_not_rehashed": counts,
                      "progress": read_json(out / "progress.json") if (out / "progress.json").exists() else None,
                      "completion_marker": (out / "COMPLETE.json").exists()}, indent=2))


def launch(args):
    out = args.out.resolve()
    if not (out / "manifest.json").exists():
        raise ValueError("Prepare the study first")
    command = [sys.executable, str(HERE / "collect.py"), "run", "--out", str(out)]
    if platform.system() == "Darwin":
        command = ["/usr/bin/caffeinate", "-i", *command]
    with (out / "supervisor.log").open("a") as log:
        child = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                                 start_new_session=True, cwd=ROOT)
    write_json(out / "launcher.json", {"launched_utc": now(), "pid": child.pid})
    print(f"Launched supervisor PID {child.pid}; inspect status and supervisor.log for actual progress.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("prepare", "run", "launch", "status"):
        p = sub.add_parser(name)
        p.add_argument("--out", type=Path, required=True)
        if name == "prepare":
            p.add_argument("--pilot", action="store_true")
            p.add_argument("--image", default="petacat-study-runtime:chez-9.5.4")
    worker = sub.add_parser("worker")
    worker.add_argument("--task", type=Path, required=True)
    worker.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "worker":
        petacat_worker(args.task, args.output)
    elif args.command == "status":
        status(args.out.resolve())
    else:
        {"prepare": prepare, "run": run_study, "launch": launch}[args.command](args)


if __name__ == "__main__":
    main()
