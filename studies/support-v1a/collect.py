#!/usr/bin/env python3
"""Crash-aware continuation of support-v1. Engine execution is remote only."""

from __future__ import annotations

import argparse
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from contextlib import contextmanager
import fcntl
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import platform
import re
import shutil
from string import Template
import subprocess
import sys
import time
import traceback

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SPEC = importlib.util.spec_from_file_location("support_v1_collect", HERE.parent / "support-v1/collect.py")
legacy = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(legacy)
now, sha, read_json, write_json = legacy.now, legacy.sha, legacy.read_json, legacy.write_json
capture, tasks_for, chunk_dir = legacy.capture, legacy.tasks_for, legacy.chunk_dir
row_identity, docker_base = legacy.row_identity, legacy.docker_base
SCOPES = legacy.SCOPES + ["studies/support-v1a"]


def protocol():
    amendment = read_json(HERE / "amendment.json")
    base = HERE.parent / "support-v1/protocol.json"
    if sha(base) != amendment["parent_protocol_sha256"]:
        raise ValueError("The frozen parent protocol changed")
    p = read_json(base)
    p.update(study_id=amendment["study_id"], schema_version=2, amendment=amendment)
    legacy.validate_protocol(p)
    return p


def source_snapshot():
    dirty = capture(["git", "status", "--porcelain", "--untracked-files=all", "--", *SCOPES], cwd=ROOT)
    if dirty:
        raise ValueError("Study inputs must be committed and clean:\n" + dirty)
    names = capture(["git", "ls-files", "-z", "--", *SCOPES], cwd=ROOT).split("\0")
    files = {name: sha(ROOT / name) for name in names if name}
    if "studies/support-v1a/collect.py" not in files:
        raise ValueError("Commit the continuation before preparation")
    return {"git_commit": capture(["git", "rev-parse", "HEAD"], cwd=ROOT),
            "git_tree": capture(["git", "rev-parse", "HEAD^{tree}"], cwd=ROOT), "files": files}


def file_inventory(directory):
    result = {}
    for path in sorted(directory.rglob("*")):
        if path.is_symlink():
            raise ValueError("Study archives must not contain symlinks")
        if path.is_file():
            result[str(path.relative_to(directory))] = sha(path)
    return result


@contextmanager
def locked(out):
    with (out / "coordinator.lock").open("a+") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ValueError("A coordinator already owns this study") from exc
        yield


def validate_rows(rows, task):
    if len(rows) != task["count"]:
        raise ValueError("Wrong number of observations")
    for i, row in enumerate(rows):
        if row.get("state") != "*ERROR*":
            one = {**task, "offset": task["offset"] + i,
                   "first_seed": task["first_seed"] + i, "count": 1}
            legacy.validate_rows([row], one)
            if row.get("error") is not None:
                raise ValueError("Ordinary outcome has error metadata")
            continue
        if any(row.get(k) != v for k, v in row_identity(task, i).items()):
            raise ValueError("Error observation identity mismatch")
        if row.get("termination") != "engine-error":
            raise ValueError("Error without engine-error termination")
        count = row.get("codelets")
        if count is not None and (type(count) is not int or not 0 <= count <= task["cap"]):
            raise ValueError("Invalid error codelet count")
        elapsed = row.get("elapsed_seconds")
        if not isinstance(elapsed, (int, float)) or not math.isfinite(elapsed) or elapsed < 0:
            raise ValueError("Invalid error duration")
        error = row.get("error", {})
        if (error.get("category") not in ("scheme-condition", "python-exception")
                or error.get("stage") not in ("clear-memory", "initialize", "run")
                or not isinstance(error.get("detail"), str) or not error["detail"]):
            raise ValueError("Missing structured engine-error evidence")


def load_completed(directory, task):
    receipt = directory / "complete.json"
    if not receipt.exists():
        return None
    info = read_json(receipt)
    if info["task"] != task or not re.fullmatch(r"attempt-\d+", info["attempt"]):
        raise ValueError("Receipt assignment mismatch")
    attempt = directory / info["attempt"]
    if sha(attempt / "runs.jsonl") != info["sha256"]:
        raise ValueError("Observation checksum mismatch")
    artifacts = info["artifacts"]
    if "runs.jsonl" not in artifacts or "attempt.json" not in artifacts:
        raise ValueError("Missing required artifact hashes")
    for name, expected in artifacts.items():
        relative = Path(name)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("Unsafe receipt artifact path")
        if sha(attempt / relative) != expected:
            raise ValueError("Artifact checksum mismatch")
    rows = [json.loads(line) for line in (attempt / "runs.jsonl").read_text().splitlines()]
    validate_rows(rows, task)
    return rows


def raw_rows(path, task):
    rows = []
    for line in path.read_text().splitlines():
        i, seed, state, count, elapsed, termination = line.split("\t")
        if int(i) != len(rows) or int(seed) != task["first_seed"] + len(rows):
            raise ValueError("Raw observation identity mismatch")
        rows.append({**row_identity(task, len(rows)), "state": state, "codelets": int(count),
                     "elapsed_seconds": int(elapsed) / 1000, "termination": termination})
    if len(rows) > task["count"]:
        raise ValueError("Too many raw observations")
    if rows:
        validate_rows(rows, {**task, "count": len(rows)})
    return rows


def signature(row):
    return {key: row.get(key) for key in ("phase", "engine", "problem", "index", "seed",
                                         "max_codelets", "state", "codelets", "termination")}


def check_prefix(out, task, rows):
    parent = out / "parent-incomplete" / chunk_dir(Path("."), task)
    for attempt in sorted(parent.glob("attempt-*")):
        if task["engine"] != "metacat" or not (attempt / "raw.tsv").exists():
            raise ValueError("Unsupported incomplete parent attempt")
        prefix = raw_rows(attempt / "raw.tsv", task)
        if [signature(r) for r in rows[:len(prefix)]] != [signature(r) for r in prefix]:
            raise ValueError("Replayed chunk changed its saved successful prefix")


def prepare(args):
    out, parent = args.out.resolve(), args.parent.resolve()
    if out.exists() or out == parent or parent in out.parents:
        raise ValueError("Use a new output directory outside the parent study")
    p = protocol()
    a = p["amendment"]
    pm = read_json(parent / "manifest.json")
    if (sha(parent / "manifest.json") != a["parent_manifest_sha256"]
            or sha(parent / "protocol.json") != a["parent_protocol_sha256"]
            or pm["source"]["git_commit"] != a["parent_commit"] or pm["pilot"]):
        raise ValueError("Wrong parent study")
    if read_json(parent / "progress.json")["state"] != "failed" or (parent / "COMPLETE.json").exists():
        raise ValueError("Parent must be the interrupted, incomplete study")
    # Open an existing lock read-only so even the parent lock file is not changed.
    with (parent / "coordinator.lock").open("r") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        source = source_snapshot()
        if any(source["files"].get(name) != value for name, value in pm["source"]["files"].items()):
            raise ValueError("Engine, inputs, or frozen parent tools changed")
        if legacy.python_runtime() != pm["python"]:
            raise ValueError("Python environment differs from parent")
        local = read_json(parent / "local.json")
        legacy.verify_reconstruction(local)
        if legacy.runtime_snapshot(local) != pm["reference_runtime"]:
            raise ValueError("Reference runtime differs from parent")
        before = file_inventory(parent)
        out.mkdir(parents=True)
        counts, receipts, attempts = {}, {}, []
        for phase in p["phases"]:
            counts[phase["name"]] = 0
            for task in tasks_for(p, phase):
                directory = chunk_dir(parent, task)
                if not directory.exists():
                    continue
                completed = load_completed(directory, task)
                destination = chunk_dir(out if completed is not None else out / "parent-incomplete", task)
                shutil.copytree(directory, destination)
                for attempt in sorted(directory.glob("attempt-*")):
                    info = read_json(attempt / "attempt.json")
                    attempts.append({"phase": task["phase"], "problem": task["problem"],
                                     "offset": task["offset"], "attempt": attempt.name,
                                     "exit_status": info.get("exit_status"),
                                     "wall_seconds": info.get("wall_seconds"),
                                     "admitted_in_parent": completed is not None})
                if completed is not None:
                    load_completed(destination, task)
                    counts[phase["name"]] += len(completed)
                    receipts[str(directory.relative_to(parent) / "complete.json")] = sha(directory / "complete.json")
        if file_inventory(parent) != before:
            raise ValueError("Parent changed during import")
        write_json(out / "parent-inventory.json", before)
        write_json(out / "parent-import.json", {"verified_utc": now(), "counts": counts,
                   "receipts": receipts, "attempts": attempts,
                   "parent_manifest_sha256": sha(parent / "manifest.json"),
                   "parent_inventory_sha256": sha(out / "parent-inventory.json"),
                   "incomplete_copy_hashes": file_inventory(out / "parent-incomplete")})
        write_json(out / "protocol.json", p)
        write_json(out / "local.json", {**local, "parent": str(parent)})
        write_json(out / "manifest.json", {"schema_version": 2, "study_id": p["study_id"],
                   "prepared_utc": now(), "pilot": False, "source": source,
                   "protocol_sha256": sha(out / "protocol.json"), "python": legacy.python_runtime(),
                   "reference_runtime": pm["reference_runtime"],
                   "numeric_environment": pm["numeric_environment"],
                   "parent_import_sha256": sha(out / "parent-import.json"),
                   "amendment_note": a["analysis_status"]})
    print(json.dumps({"prepared": str(out), "verified_inherited_runs": counts}, indent=2), flush=True)


def verify_study(out, runtime=True):
    manifest, p = read_json(out / "manifest.json"), read_json(out / "protocol.json")
    if p != protocol() or sha(out / "protocol.json") != manifest["protocol_sha256"]:
        raise ValueError("Continuation protocol changed")
    if source_snapshot() != manifest["source"] or legacy.python_runtime() != manifest["python"]:
        raise ValueError("Continuation code or Python environment changed")
    if sha(out / "parent-import.json") != manifest["parent_import_sha256"]:
        raise ValueError("Parent import changed")
    imported = read_json(out / "parent-import.json")
    if sha(out / "parent-inventory.json") != imported["parent_inventory_sha256"]:
        raise ValueError("Parent inventory changed")
    if any(sha(out / name) != digest for name, digest in imported["receipts"].items()):
        raise ValueError("Inherited parent receipt changed")
    if file_inventory(out / "parent-incomplete") != imported["incomplete_copy_hashes"]:
        raise ValueError("Preserved incomplete attempts changed")
    local = read_json(out / "local.json")
    legacy.verify_reconstruction(local)
    if runtime and legacy.runtime_snapshot(local) != manifest["reference_runtime"]:
        raise ValueError("Reference runtime changed")
    return manifest, p, local


def scheme_script(task):
    initial, modified, target = task["strings"]
    return Template((HERE / "collector.ss.in").read_text()).substitute(
        count=task["count"], first_seed=task["first_seed"], cap=task["cap"],
        initial=initial, modified=modified, target=target)


def scheme_segment(segment, task, local, timeout):
    (segment / "collector.ss").write_text(scheme_script(task))
    name = "support-v1a-" + hashlib.sha256(str(segment).encode()).hexdigest()[:20]
    command = [*docker_base(local), "--name", name, "-v", f"{local['source']}:/metacat:ro",
               "-v", f"{segment}:/out", "-w", "/metacat", "--entrypoint", "env",
               local["image"], "-u", "DISPLAY", "scheme", "-q", "--script", "/out/collector.ss"]
    try:
        with (segment / "stdout.log").open("w") as stdout, (segment / "stderr.log").open("w") as stderr:
            result = subprocess.run(command, stdout=stdout, stderr=stderr, timeout=timeout)
    except BaseException:
        subprocess.run([local["docker"], "stop", "-t", "5", name], capture_output=True)
        raise
    rows = raw_rows(segment / "raw.tsv", task) if (segment / "raw.tsv").exists() else []
    marker = segment / "engine-error.tsv"
    if result.returncode == 0:
        if marker.exists():
            raise ValueError("Successful exit with an error marker")
        validate_rows(rows, task)
        return rows, 0
    if result.returncode != 86 or not marker.exists() or not (segment / "condition.txt").exists():
        raise RuntimeError(f"Unclassified Scheme/infrastructure exit {result.returncode}")
    index, seed, stage, count, elapsed = marker.read_text().strip().split("\t")
    if int(index) != len(rows) or int(seed) != task["first_seed"] + len(rows) or len(rows) >= task["count"]:
        raise ValueError("Engine-error marker identity mismatch")
    rows.append({**row_identity(task, len(rows)), "state": "*ERROR*", "termination": "engine-error",
                 "codelets": None if count == "unknown" else int(count),
                 "elapsed_seconds": int(elapsed) / 1000,
                 "error": {"category": "scheme-condition", "stage": stage,
                           "detail": (segment / "condition.txt").read_text().strip()}})
    validate_rows(rows, {**task, "count": len(rows)})
    return rows, 86


def petacat_worker(task_path, output):
    task = read_json(task_path)
    os.environ["PETACAT_NUMERIC_BACKEND"] = task["backend"]
    sys.path.insert(0, str(ROOT))
    from server.engine.metadata import MetadataProvider
    from server.engine.runner import EngineRunner, STATUS_ANSWER_FOUND, STATUS_GAVE_UP, STATUS_HALTED
    meta = MetadataProvider.from_seed_data(str(ROOT / "seed_data"))
    with output.open("x") as stream:
        for i in range(task["count"]):
            started, stage, runner = time.perf_counter(), "initialize", None
            try:
                runner = EngineRunner(meta)
                runner.init_mcat(*task["strings"], seed=task["first_seed"] + i)
                stage = "run"
                runner.run_mcat(max_steps=task["cap"])
            except (OSError, MemoryError, ImportError):
                raise
            except Exception as exc:
                row = {**row_identity(task, i), "state": "*ERROR*", "termination": "engine-error",
                       "codelets": runner.ctx.codelet_count if stage == "run" else None,
                       "elapsed_seconds": time.perf_counter() - started,
                       "error": {"category": "python-exception", "stage": stage,
                                 "detail": f"{type(exc).__name__}: {exc}"}}
                traceback.print_exc()
                stream.write(json.dumps(row, sort_keys=True) + "\n")
                stream.flush()
                return 86
            count = runner.ctx.codelet_count
            if runner.status == STATUS_ANSWER_FOUND and runner.ctx.workspace.answer_string is not None:
                state = runner.ctx.workspace.answer_string.text
            elif runner.status == STATUS_HALTED and count == task["cap"]:
                state = "*CAP*"
            elif runner.status == STATUS_GAVE_UP:
                state = "*NONE*"
            else:
                raise ValueError(f"Unclassified terminal state {runner.status} at {count}")
            row = {**row_identity(task, i), "state": state, "codelets": count,
                   "termination": runner.status, "elapsed_seconds": time.perf_counter() - started}
            stream.write(json.dumps(row, sort_keys=True) + "\n")
            stream.flush()
    return 0


def python_segment(segment, task, manifest, timeout):
    env = dict(os.environ, **manifest["numeric_environment"])
    command = [sys.executable, str(HERE / "collect.py"), "worker", "--task", str(segment / "task.json"),
               "--output", str(segment / "runs.jsonl")]
    with (segment / "stdout.log").open("w") as stdout, (segment / "stderr.log").open("w") as stderr:
        result = subprocess.run(command, stdout=stdout, stderr=stderr, timeout=timeout, env=env)
    if result.returncode not in (0, 86):
        raise RuntimeError(f"Unclassified Python/infrastructure exit {result.returncode}")
    rows = [json.loads(line) for line in (segment / "runs.jsonl").read_text().splitlines()]
    if len(rows) > task["count"]:
        raise ValueError("Python segment exceeded its assignment")
    if result.returncode == 86:
        if not rows or rows[-1]["state"] != "*ERROR*" or any(r["state"] == "*ERROR*" for r in rows[:-1]):
            raise ValueError("Missing Python engine-error evidence")
        validate_rows(rows, {**task, "count": len(rows)})
    else:
        validate_rows(rows, task)
        if any(r["state"] == "*ERROR*" for r in rows):
            raise ValueError("Python success exit with error record")
    return rows, result.returncode


def execute_task(out, task, local, manifest, timeout):
    directory = chunk_dir(out, task)
    directory.mkdir(parents=True, exist_ok=True)
    previous = load_completed(directory, task)
    if previous is not None:
        return len(previous), sum(r["state"] == "*ERROR*" for r in previous)
    number = 1 + max([int(p.name.split("-")[1]) for p in directory.glob("attempt-*")], default=0)
    attempt = directory / f"attempt-{number:03d}"
    attempt.mkdir()
    write_json(attempt / "task.json", task)
    started = time.monotonic()
    metadata = {"started_utc": now(), "task": task, "attempt": attempt.name}
    write_json(attempt / "attempt.json", metadata)
    try:
        rows, segments = [], []
        while len(rows) < task["count"]:
            subtask = {**task, "offset": task["offset"] + len(rows),
                       "first_seed": task["first_seed"] + len(rows), "count": task["count"] - len(rows)}
            segment = attempt / f"segment-{len(segments):03d}"
            segment.mkdir()
            write_json(segment / "task.json", subtask)
            remaining = timeout - (time.monotonic() - started)
            if remaining <= 0:
                raise TimeoutError("Chunk exceeded the operational time limit")
            segment_start = time.monotonic()
            collected, code = (scheme_segment(segment, subtask, local, remaining)
                               if task["engine"] == "metacat"
                               else python_segment(segment, subtask, manifest, remaining))
            if not collected or len(collected) > subtask["count"]:
                raise ValueError("Segment made invalid progress")
            rows.extend(collected)
            segments.append({"segment": segment.name, "exit_status": code,
                             "runs": len(collected), "wall_seconds": time.monotonic() - segment_start})
            write_json(segment / "segment.json", segments[-1])
        validate_rows(rows, task)
        check_prefix(out, task, rows)
        diagnostic = chunk_dir(out / "preflight", task)
        if (diagnostic / "complete.json").exists():
            expected = load_completed(diagnostic, task)
            if [signature(r) for r in rows] != [signature(r) for r in expected]:
                raise ValueError("Main replay differs from the excluded preflight chunk")
        with (attempt / "runs.jsonl").open("x") as stream:
            for row in rows:
                stream.write(json.dumps(row, sort_keys=True) + "\n")
        errors = sum(r["state"] == "*ERROR*" for r in rows)
        metadata.update(finished_utc=now(), wall_seconds=time.monotonic() - started,
                        exit_status=0, runs=len(rows), engine_errors=errors, segments=segments)
        write_json(attempt / "attempt.json", metadata)
        write_json(directory / "complete.json", {**metadata, "sha256": sha(attempt / "runs.jsonl"),
                                                  "artifacts": file_inventory(attempt)})
        return len(rows), errors
    except BaseException as exc:
        metadata.update(finished_utc=now(), wall_seconds=time.monotonic() - started,
                        exit_status=1, error_type=type(exc).__name__, error=str(exc))
        write_json(attempt / "attempt.json", metadata)
        raise RuntimeError(f"Failed {task['phase']}/{task['problem']}/{task['offset']}; inspect attempt logs") from exc


def preflight(args):
    out = args.out.resolve()
    with locked(out):
        manifest, p, local = verify_study(out)
        root = out / "preflight"
        if root.exists():
            raise ValueError("Preflight already exists; preserve it and investigate before retrying")
        root.mkdir()
        checks = []
        cfg = p["amendment"]["preflight"]
        phase = p["phases"][0]
        for task in tasks_for(p, phase):
            if task["offset"] != 0:
                break
            expected = load_completed(chunk_dir(out, task), task)
            if expected is None:
                raise ValueError("Missing inherited preflight comparison chunk")
            for offset, count in ((0, cfg["construction_first_chunk_prefix_per_input"]),
                                  (cfg["construction_first_chunk_interior_offset"],
                                   cfg["construction_first_chunk_interior_count"])):
                sample = {**task, "offset": offset, "first_seed": task["first_seed"] + offset, "count": count}
                execute_task(root, sample, local, manifest, p["chunk_timeout_seconds"])
                observed = load_completed(chunk_dir(root, sample), sample)
                if [signature(r) for r in observed] != [signature(r) for r in expected[offset:offset + count]]:
                    raise ValueError("Amended collector or fresh-process replay changed ordinary behavior")
                checks.append({"problem": task["problem"], "offset": offset, "matched": count})
            print(f"Preflight matched prefix and interior: {task['problem']}", flush=True)
        failure = p["amendment"]["known_failure"]
        phase = next(x for x in p["phases"] if x["name"] == failure["phase"])
        task = next(t for t in tasks_for(p, phase)
                    if t["problem"] == failure["problem"] and t["offset"] == failure["chunk_offset"])
        saved = chunk_dir(out / "parent-incomplete", task) / "attempt-001/raw.tsv"
        if len(raw_rows(saved, task)) != failure["successful_prefix_rows"]:
            raise ValueError("Unexpected length of the preserved failed-chunk prefix")
        execute_task(root, task, local, manifest, p["chunk_timeout_seconds"])
        rows = load_completed(chunk_dir(root, task), task)
        check_prefix(out, task, rows)
        errors = [r for r in rows if r["state"] == "*ERROR*"]
        if (len(errors) != 1 or errors[0]["seed"] != failure["seed"]
                or "non-procedure" not in errors[0]["error"]["detail"]):
            raise ValueError("Known failing chunk did not reproduce the expected engine error")
        # The post-error suffix must agree with separate fresh-process executions.
        suffix = [r for r in rows if r["index"] > failure["index"]]
        for row in suffix:
            sample = {**task, "offset": row["index"], "first_seed": row["seed"], "count": 1}
            execute_task(root, sample, local, manifest, p["chunk_timeout_seconds"])
            fresh = load_completed(chunk_dir(root, sample), sample)[0]
            if signature(fresh) != signature(row):
                raise ValueError("Post-error suffix differs under fresh-process replay")
        record = {"completed_utc": now(), "ordinary_checks": checks,
                  "saved_failed_prefix_matched": failure["successful_prefix_rows"],
                  "known_error": errors[0], "fresh_suffix_checks": len(suffix),
                  "main_observations": 0, "artifacts": file_inventory(root)}
        write_json(out / "preflight.json", record)
        print(json.dumps({k: v for k, v in record.items() if k != "artifacts"}, indent=2), flush=True)


def verify_preflight(out):
    record = read_json(out / "preflight.json")
    if file_inventory(out / "preflight") != record["artifacts"]:
        raise ValueError("Preflight evidence changed")
    if record["main_observations"] != 0:
        raise ValueError("Preflight must remain excluded")


def run_study(args):
    out = args.out.resolve()
    with locked(out):
        manifest, p, local = verify_study(out)
        verify_preflight(out)
        if (out / "COMPLETE.json").exists():
            print("Collection already complete; use analyze.py to verify it")
            return
        total = sum(x["runs_per_problem"] * len(p["problems"]) for x in p["phases"])
        progress = {"started_utc": now(), "total_runs": total, "completed_runs": 0, "engine_errors": 0}
        inventory = {}
        try:
            for phase in p["phases"]:
                assignments, todo = list(tasks_for(p, phase)), []
                for task in assignments:
                    rows = load_completed(chunk_dir(out, task), task)
                    if rows is None:
                        todo.append(task)
                    else:
                        progress["completed_runs"] += len(rows)
                        progress["engine_errors"] += sum(r["state"] == "*ERROR*" for r in rows)
                progress["phase"] = phase["name"]
                pending_tasks, failure = iter(todo), None
                with ThreadPoolExecutor(max_workers=p["workers"]) as pool:
                    pending = {}
                    while True:
                        stopping = (out / "STOP").exists()
                        while not stopping and failure is None and len(pending) < p["workers"]:
                            task = next(pending_tasks, None)
                            if task is None:
                                break
                            pending[pool.submit(execute_task, out, task, local, manifest,
                                                p["chunk_timeout_seconds"])] = task
                        progress.update(heartbeat_utc=now(), active_chunks=len(pending),
                                        state="draining-after-failure" if failure else "stopping" if stopping else "running")
                        write_json(out / "progress.json", progress)
                        if not pending:
                            if failure:
                                raise failure
                            if stopping:
                                progress.update(state="stopped", active_chunks=0)
                                write_json(out / "progress.json", progress)
                                return
                            break
                        done, _ = wait(pending, timeout=10, return_when=FIRST_COMPLETED)
                        for future in done:
                            task = pending.pop(future)
                            try:
                                count, errors = future.result()
                            except Exception as exc:
                                failure = failure or exc
                                progress["error"] = str(failure)
                            else:
                                progress["completed_runs"] += count
                                progress["engine_errors"] += errors
                                print(f"{now()} {phase['name']} {task['problem']} {task['offset']} "
                                      f"{progress['completed_runs']}/{total} errors={progress['engine_errors']}", flush=True)
                for task in assignments:
                    directory = chunk_dir(out, task)
                    if load_completed(directory, task) is None:
                        raise ValueError("Phase ended with missing observations")
                    inventory[str(directory.relative_to(out) / "complete.json")] = sha(directory / "complete.json")
                verify_study(out, runtime=False)
            write_json(out / "COMPLETE.json", {"completed_utc": now(), "total_runs": total,
                       "manifest_sha256": sha(out / "manifest.json"), "receipts": inventory,
                       "preflight_sha256": sha(out / "preflight.json"), "engine_errors": progress["engine_errors"]})
            progress.update(state="complete", heartbeat_utc=now(), active_chunks=0)
            write_json(out / "progress.json", progress)
        except BaseException as exc:
            progress.update(state="failed", heartbeat_utc=now(), active_chunks=0, error=str(exc))
            write_json(out / "progress.json", progress)
            raise


def status(out):
    p = read_json(out / "protocol.json")
    counts = {phase["name"]: sum(task["count"] for task in tasks_for(p, phase)
                               if (chunk_dir(out, task) / "complete.json").exists()) for phase in p["phases"]}
    print(json.dumps({"receipted_runs_not_rehashed": counts,
                      "progress": read_json(out / "progress.json") if (out / "progress.json").exists() else None,
                      "analysis": read_json(out / "analysis-status.json") if (out / "analysis-status.json").exists() else None,
                      "completion_marker": (out / "COMPLETE.json").exists()}, indent=2))


def launch(args):
    out = args.out.resolve()
    if not (out / "preflight.json").exists():
        raise ValueError("Prepare and pass preflight before launching")
    command = [sys.executable, str(HERE / "collect.py"), "supervise", "--out", str(out)]
    if platform.system() == "Darwin":
        command = ["/usr/bin/caffeinate", "-i", *command]
    with (out / "supervisor.log").open("a") as log:
        child = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                                 start_new_session=True, cwd=ROOT)
    write_json(out / "launcher.json", {"launched_utc": now(), "pid": child.pid})
    print(f"Launched supervisor PID {child.pid}; check status for actual progress.")


def supervise(args):
    run_study(args)
    out = args.out.resolve()
    if (out / "COMPLETE.json").exists():
        write_json(out / "analysis-status.json", {"state": "running", "started_utc": now()})
        try:
            subprocess.run([sys.executable, str(HERE / "analyze.py"), str(out)], check=True)
        except subprocess.CalledProcessError:
            write_json(out / "analysis-status.json", {"state": "failed", "finished_utc": now()})
            raise
        write_json(out / "analysis-status.json", {"state": "complete", "finished_utc": now(),
                   "analysis_sha256": sha(out / "analysis.json"), "report_sha256": sha(out / "RESULTS.md")})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("prepare", "preflight", "run", "launch", "status", "supervise", "audit-parent"):
        p = sub.add_parser(name)
        p.add_argument("--out", type=Path, required=True)
        if name == "prepare":
            p.add_argument("--parent", type=Path, required=True)
    worker = sub.add_parser("worker")
    worker.add_argument("--task", type=Path, required=True)
    worker.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "worker":
        sys.exit(petacat_worker(args.task, args.output))
    elif args.command == "status":
        status(args.out.resolve())
    elif args.command == "audit-parent":
        out = args.out.resolve()
        local = read_json(out / "local.json")
        if file_inventory(Path(local["parent"])) != read_json(out / "parent-inventory.json"):
            raise ValueError("Original study files changed after import")
        print("PASS original parent file inventory unchanged")
    else:
        {"prepare": prepare, "preflight": preflight, "run": run_study,
         "launch": launch, "supervise": supervise}[args.command](args)


if __name__ == "__main__":
    main()
