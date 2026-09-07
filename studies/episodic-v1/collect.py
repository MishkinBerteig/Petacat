#!/usr/bin/env python3
"""Bounded, resumable episodic collection. Engine executions belong on the study host."""

from __future__ import annotations

import argparse
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from contextlib import contextmanager
import csv
import fcntl
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import shutil
from string import Template
import subprocess
import sys
import time
import traceback

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
from outcomes import PROJECTIONS, answer_outcome, compare, key, population, reduce_answers, stopping_history

SPEC = importlib.util.spec_from_file_location("episodic_legacy", HERE.parent / "support-v1/collect.py")
legacy = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(legacy)
now, sha, read_json, write_json = legacy.now, legacy.sha, legacy.read_json, legacy.write_json
capture = legacy.capture
SCOPES = ["server/engine", "seed_data", "Metacat", "studies/support-v1", "pyproject.toml"]
NUMERIC_ENV = {"PETACAT_NUMERIC_BACKEND": "numpy", "PYTHONHASHSEED": "0",
               "OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1", "VECLIB_MAXIMUM_THREADS": "1"}


def validate_protocol(p):
    if (p.get("schema_version") != 1 or p.get("study_kind") not in ("smoke", "main")
            or p.get("population") != "unordered-tied-answer-sets"
            or p.get("projections") != list(PROJECTIONS) or p.get("backend") != "numpy"):
        raise ValueError("Unsupported study kind, population, projection, or backend")
    positive = [p[k] for k in ("episode_runs", "max_codelets", "workers", "episode_timeout_seconds",
                               "invocation_timeout_seconds", "validation_episodes", "port_episodes", "seed_stride")]
    c = p["construction"]
    positive += [c[k] for k in ("min_episodes", "max_episodes", "checkpoint_every", "consecutive_checkpoints")]
    if any(type(x) is not int or x <= 0 for x in positive):
        raise ValueError("Counts, budgets, and operational limits must be positive integers")
    if (not isinstance(c["singleton_threshold"], (float, int))
            or not 0 < c["singleton_threshold"] < 1
            or c["min_episodes"] > c["max_episodes"]
            or any(c[k] % c["checkpoint_every"] for k in ("min_episodes", "max_episodes"))):
        raise ValueError("Invalid threshold or checkpoint schedule")
    if set(p["seed_bases"]) != {"construction", "validation", "port"}:
        raise ValueError("Declare disjoint seed blocks for all three phases")
    if not p["problems"] or len({x["name"] for x in p["problems"]}) != len(p["problems"]):
        raise ValueError("Problems must be nonempty and unique")
    intervals = []
    for index, problem in enumerate(p["problems"]):
        if (not re.fullmatch(r"[a-zA-Z0-9.-]+", problem["name"])
                or len(problem["strings"]) != 3
                or not all(re.fullmatch(r"[a-z]+", s) for s in problem["strings"])):
            raise ValueError("Unsafe problem identifier or invalid letter strings")
        for phase, count in (("construction", c["max_episodes"]),
                             ("validation", p["validation_episodes"]), ("port", p["port_episodes"])):
            start = p["seed_bases"][phase] + index * p["seed_stride"]
            end = start + count * p["episode_runs"]
            if type(start) is not int or not 0 < start < end <= 2**32 or end - start > p["seed_stride"]:
                raise ValueError("Invalid or overflowing episode seed allocation")
            intervals.append((start, end))
    intervals.sort()
    if any(a[1] > b[0] for a, b in zip(intervals, intervals[1:])):
        raise ValueError("Overlapping seed blocks")
    if p["study_kind"] == "smoke" and (
            len(p["problems"]) > 3 or c["max_episodes"] > 20 or p["episode_runs"] > 8
            or p["max_codelets"] > 100000 or p["validation_episodes"] > 4 or p["port_episodes"] > 4
            or p["workers"] > 2 or p["episode_timeout_seconds"] > 300
            or p["invocation_timeout_seconds"] > 1800 or c["singleton_threshold"] < 0.1):
        raise ValueError("Smoke configuration exceeds hard safety limits; no automatic escalation to main")


def authorize_main(p, allowed):
    if p["study_kind"] == "main" and not allowed:
        raise ValueError("Main studies require explicit --allow-full-experiment at prepare AND run")


def source_snapshot(require_clean=False):
    names = capture(["git", "ls-files", "-z", "--", *SCOPES], cwd=ROOT).split("\0")
    paths = {name for name in names if name}
    paths.update(str(p.relative_to(ROOT)) for p in HERE.iterdir() if p.is_file() and p.name != ".DS_Store")
    dirty = capture(["git", "status", "--porcelain", "--untracked-files=all", "--",
                     *SCOPES, "studies/episodic-v1"], cwd=ROOT)
    if require_clean and dirty:
        raise ValueError("Main study inputs must be committed and clean")
    return {"git_commit": capture(["git", "rev-parse", "HEAD"], cwd=ROOT),
            "development_snapshot": bool(dirty), "files": {name: sha(ROOT / name) for name in sorted(paths)}}


@contextmanager
def locked(out):
    with (out / "coordinator.lock").open("a+") as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ValueError("Another coordinator owns this study") from exc
        yield


def task_for(p, phase, problem_index, episode):
    problem = p["problems"][problem_index]
    return {"phase": phase, "engine": "petacat" if phase == "port" else "metacat",
            "problem": problem["name"], "strings": problem["strings"], "episode": episode,
            "first_seed": p["seed_bases"][phase] + problem_index * p["seed_stride"] + episode * p["episode_runs"],
            "episode_runs": p["episode_runs"], "max_codelets": p["max_codelets"]}


def directory_for(out, task):
    return out / "episodes" / task["phase"] / task["problem"] / f"{task['episode']:08d}"


def validate_row(row, task):
    allowed = {"task", "status", "outcomes", "winners", "attempted_runs", "answer_runs",
               "capped_runs", "answerless_runs", "codelets", "elapsed_seconds", "error", "error_step"}
    if set(row) - allowed:
        raise ValueError("Unexpected episode fields; ordered trajectories are not part of this dataset")
    if row.get("task") != task or set(row.get("outcomes", {})) != set(PROJECTIONS):
        raise ValueError("Episode identity or projections do not match assignment")
    counts = [row.get(k) for k in ("attempted_runs", "answer_runs", "capped_runs", "answerless_runs", "codelets")]
    if any(type(n) is not int or n < 0 for n in counts):
        raise ValueError("Invalid episode accounting")
    attempted, answered, capped, empty, codelets = counts
    if attempted > task["episode_runs"] or codelets > attempted * task["max_codelets"]:
        raise ValueError("Episode exceeded its fixed budget")
    if row.get("status") == "complete":
        if attempted != task["episode_runs"] or answered + capped + empty != attempted or row.get("error"):
            raise ValueError("Incomplete or inconsistent ordinary episode")
    elif row.get("status") == "engine-error":
        if (not isinstance(row.get("error"), dict) or not row["error"].get("detail")
                or row["error"].get("stage") not in ("clear-memory", "initialize", "run")
                or type(row.get("error_step")) is not int
                or not 0 <= row["error_step"] < task["episode_runs"]
                or answered + capped + empty != max(0, attempted - 1)):
            raise ValueError("Incomplete engine-error evidence")
    else:
        raise ValueError("Unclassified terminal state")
    elapsed = row.get("elapsed_seconds")
    if not isinstance(elapsed, (int, float)) or not math.isfinite(elapsed) or elapsed < 0:
        raise ValueError("Invalid execution time")
    if set(row.get("winners", {})) != set(PROJECTIONS):
        raise ValueError("Missing selected-answer evidence")
    for projection in PROJECTIONS:
        outcome, winners = row["outcomes"][projection], row["winners"][projection]
        if not isinstance(winners, list) or len(winners) > answered:
            raise ValueError("Invalid number of winning answer occurrences")
        if row["status"] == "engine-error":
            if outcome != {"kind": "engine-error"} or winners:
                raise ValueError("Failed episode must not masquerade as a complete best-answer result")
            continue
        if not answered:
            if outcome != {"kind": "no-answer"} or winners:
                raise ValueError("No-answer episode has a fictitious winner")
            continue
        if not winners or outcome != answer_outcome(w["answer"] for w in winners):
            raise ValueError("Outcome differs from its selected-answer evidence")
        for winner in winners:
            if not re.fullmatch(r"[a-z]+", winner["answer"]):
                raise ValueError("Invalid answer letters")
            if any(not isinstance(winner[k], (float, int)) or not math.isfinite(winner[k])
                   or not 0 <= winner[k] <= 100
                   for k in ("quality", "temperature", "rule_abstractness", "theme_abstractness")):
                raise ValueError("Invalid selected-answer score")
            if (type(winner["coherent"]) is not bool
                    or any(type(winner[k]) is not int or winner[k] < 0
                           for k in ("theme_count", "unjustified_count"))
                    or winner["unjustified_count"] > winner["theme_count"]):
                raise ValueError("Invalid selected-answer conceptual summary")
        if projection == "quality" and len({w["quality"] for w in winners}) != 1:
            raise ValueError("Quality co-winners have unequal scores")


def load_completed(out, task):
    directory = directory_for(out, task)
    if not (directory / "complete.json").exists():
        return None
    receipt = read_json(directory / "complete.json")
    if receipt["task"] != task or not re.fullmatch(r"attempt-\d+", receipt["attempt"]):
        raise ValueError("Receipt assignment mismatch")
    attempt = directory / receipt["attempt"]
    if not {"episode.json", "task.json", "attempt.json"} <= set(receipt["files"]):
        raise ValueError("Incomplete receipt")
    for name, expected in receipt["files"].items():
        if Path(name).name != name or sha(attempt / name) != expected:
            raise ValueError("Episode artifact checksum mismatch")
    row = read_json(attempt / "episode.json")
    validate_row(row, task)
    return row


def scheme_row(attempt, task):
    with (attempt / "raw.tsv").open(newline="") as stream:
        rows = list(csv.reader(stream, delimiter="\t"))
    if not rows or len(rows[0]) != 8 or rows[0][0] != "EP":
        raise ValueError("Missing or invalid compact Scheme episode record")
    _, status, attempted, answered, caps, empty, codelets, error_step = rows[0]
    result = {"task": task, "status": status, "attempted_runs": int(attempted),
              "answer_runs": int(answered), "capped_runs": int(caps), "answerless_runs": int(empty),
              "codelets": int(codelets), "winners": {p: [] for p in PROJECTIONS}}
    for fields in rows[1:]:
        if len(fields) != 11 or fields[0] != "DESC" or fields[1] not in PROJECTIONS:
            raise ValueError("Invalid selected-description row")
        _, projection, answer, quality, temperature, abstractness, theme_abstractness, coherent, unjustified, theme_count, themes = fields
        if coherent not in ("0", "1"):
            raise ValueError("Invalid coherence flag")
        result["winners"][projection].append({"answer": answer, "quality": float(quality),
            "temperature": float(temperature), "rule_abstractness": float(abstractness),
            "theme_abstractness": float(theme_abstractness), "coherent": coherent == "1",
            "unjustified_count": int(unjustified), "theme_count": int(theme_count),
            "themes": themes.split(";") if themes else []})
    result["winners"] = {p: sorted(v, key=key) for p, v in result["winners"].items()}
    if status == "engine-error":
        result["error_step"] = int(error_step)
        # The marker records the stage separately so no Scheme condition prose is parsed.
        stage = (attempt / "error-stage.txt").read_text().strip()
        result["error"] = {"category": "scheme-condition", "stage": stage,
                           "detail": (attempt / "condition.txt").read_text().strip()}
        result["outcomes"] = {p: {"kind": "engine-error"} for p in PROJECTIONS}
    else:
        if int(error_step) != -1 or (attempt / "condition.txt").exists():
            raise ValueError("Ordinary Scheme result contains error evidence")
        result["outcomes"] = {p: answer_outcome(w["answer"] for w in result["winners"][p]) for p in PROJECTIONS}
    return result


def petacat_worker(task_path, output):
    os.environ.update(NUMERIC_ENV)
    sys.path.insert(0, str(ROOT))
    from server.engine.metadata import MetadataProvider
    from server.engine.memory import EpisodicMemory
    from server.engine.runner import EngineRunner, STATUS_ANSWER_FOUND, STATUS_GAVE_UP, STATUS_HALTED
    from server.engine.answer_comparison import AnswerComparison, all_themes_of, snag_justified_themes, unjustified_of
    from outcomes import preference

    class IdentifiedComparison(AnswerComparison):
        def _better(self, section, first, intro, reason):
            result = super()._better(section, first, intro, reason)
            result["study_side"] = -1 if first else 1
            return result

    task = read_json(task_path)
    meta = MetadataProvider.from_seed_data(str(ROOT / "seed_data"))
    memory = EpisodicMemory()
    row = {"task": task, "status": "complete", "attempted_runs": 0, "answer_runs": 0,
           "capped_runs": 0, "answerless_runs": 0, "codelets": 0}
    start = time.perf_counter()
    for index in range(task["episode_runs"]):
        stage, runner = "initialize", None
        before = len(memory.answers)
        row["attempted_runs"] += 1
        try:
            runner = EngineRunner(meta)
            runner.init_mcat(*task["strings"], seed=task["first_seed"] + index, memory=memory)
            stage = "run"
            runner.run_mcat(max_steps=task["max_codelets"])
        except (OSError, MemoryError, ImportError):
            raise
        except Exception as exc:
            traceback.print_exc()
            if stage == "run":
                row["codelets"] += runner.ctx.codelet_count
            row.update(status="engine-error", error_step=index,
                       error={"category": "python-exception", "stage": stage, "detail": f"{type(exc).__name__}: {exc}"})
            break
        count = runner.ctx.codelet_count
        row["codelets"] += count
        if runner.status == STATUS_ANSWER_FOUND and len(memory.answers) == before + 1:
            row["answer_runs"] += 1
        elif len(memory.answers) != before:
            raise ValueError("Answer status and memory insertion disagree")
        elif runner.status == STATUS_HALTED and count == task["max_codelets"]:
            row["capped_runs"] += 1
        elif runner.status == STATUS_GAVE_UP:
            row["answerless_runs"] += 1
        else:
            raise ValueError(f"Unclassified run terminal state {runner.status}")
    if row["status"] == "engine-error":
        row["outcomes"] = {p: {"kind": "engine-error"} for p in PROJECTIONS}
        row["winners"] = {p: [] for p in PROJECTIONS}
    else:
        answers = list(memory.answers)
        summaries = []
        for a in answers:
            all_themes = all_themes_of(a)
            justified = snag_justified_themes(a, memory)
            summaries.append({"answer": a.problem[3], "quality": float(a.quality),
                "temperature": float(a.temperature), "rule_abstractness": float(a.top_rule_abstractness),
                "theme_abstractness": float(a.theme_abstractness), "coherent": a.is_coherent,
                "theme_count": len(all_themes),
                "unjustified_count": len([x for x in unjustified_of(a) if x not in justified]),
                "themes": sorted(f"{d}={r if r == 'diff' or r.startswith('plato-') else 'plato-' + r}"
                                 for d, r in all_themes)})

        def judge(i, j):
            comparison = IdentifiedComparison(answers[i], answers[j], memory, meta=meta)
            side = comparison.verdict().get("study_side", 0)
            expected = preference(summaries[i], summaries[j], comparison.num_rule_differences != -1,
                                  not comparison.theme_differences)
            if side != expected:
                raise ValueError("Native port verdict differs from independent selection specification")
            return side

        row["outcomes"], row["winners"] = reduce_answers(summaries, judge)
    row["elapsed_seconds"] = time.perf_counter() - start
    validate_row(row, task)
    write_json(output, row)
    return 86 if row["status"] == "engine-error" else 0


def execute_task(out, task, local, manifest, timeout, retry=False):
    existing = load_completed(out, task)
    if existing is not None:
        return existing
    directory = directory_for(out, task)
    directory.mkdir(parents=True, exist_ok=True)
    prior = sorted(directory.glob("attempt-*"))
    if prior and not retry:
        raise ValueError("An incomplete attempt exists; review it before --retry-incomplete")
    attempt = directory / f"attempt-{len(prior) + 1:03d}"
    attempt.mkdir()
    write_json(attempt / "task.json", task)
    metadata = {"task": task, "started_utc": now()}
    write_json(attempt / "attempt.json", metadata)
    started, container_name = time.monotonic(), None
    try:
        if task["engine"] == "metacat":
            (attempt / "collector.ss").write_text(Template((HERE / "collector.ss.in").read_text()).substitute(
                episode_runs=task["episode_runs"], first_seed=task["first_seed"], cap=task["max_codelets"],
                initial=task["strings"][0], modified=task["strings"][1], target=task["strings"][2]))
            container_name = "episodic-v1-" + hashlib.sha256(str(attempt).encode()).hexdigest()[:20]
            command = [*legacy.docker_base(local), "--name", container_name,
                       "-v", f"{local['source']}:/metacat:ro", "-v", f"{HERE}:/study:ro",
                       "-v", f"{attempt}:/out", "-w", "/metacat", "--entrypoint", "env",
                       local["image"], "-u", "DISPLAY", "scheme", "-q", "--script", "/out/collector.ss"]
        else:
            command = [sys.executable, str(HERE / "collect.py"), "worker", "--task", str(attempt / "task.json"),
                       "--output", str(attempt / "episode.json")]
        with (attempt / "stdout.log").open("w") as stdout, (attempt / "stderr.log").open("w") as stderr:
            result = subprocess.run(command, stdout=stdout, stderr=stderr,
                                    timeout=timeout, env=dict(os.environ, **NUMERIC_ENV))
        if result.returncode not in (0, 86):
            raise RuntimeError(f"Unclassified engine/infrastructure exit {result.returncode}")
        row = scheme_row(attempt, task) if task["engine"] == "metacat" else read_json(attempt / "episode.json")
        row["elapsed_seconds"] = time.monotonic() - started
        validate_row(row, task)
        if (result.returncode == 86) != (row["status"] == "engine-error"):
            raise ValueError("Exit status and episode status disagree")
        write_json(attempt / "episode.json", row)
        metadata.update(finished_utc=now(), wall_seconds=time.monotonic() - started,
                        exit_status=result.returncode, admitted=True)
        write_json(attempt / "attempt.json", metadata)
        write_json(directory / "complete.json", {"task": task, "attempt": attempt.name,
                   "files": {p.name: sha(p) for p in sorted(attempt.iterdir()) if p.is_file()}})
        return row
    except BaseException as exc:
        if container_name:
            subprocess.run([local["docker"], "stop", "-t", "2", container_name], capture_output=True, timeout=30)
        metadata.update(finished_utc=now(), admitted=False, error_type=type(exc).__name__, error=str(exc))
        write_json(attempt / "attempt.json", metadata)
        raise


def prepare(args):
    p = read_json(args.protocol)
    validate_protocol(p)
    authorize_main(p, args.allow_full_experiment)
    out = args.out.resolve()
    if out.exists():
        raise ValueError("Refusing to overwrite an existing study directory")
    source = source_snapshot(require_clean=p["study_kind"] == "main")
    docker = shutil.which("docker")
    if not docker:
        raise ValueError("Docker must be on PATH")
    local = {"docker": docker, "image": capture([docker, "image", "inspect", args.image, "--format", "{{.Id}}"]),
             "source": str((ROOT / "Metacat/build/source").resolve())}
    legacy.verify_reconstruction(local)
    runtime = legacy.runtime_snapshot(local)
    out.mkdir(parents=True)
    write_json(out / "protocol.json", p)
    write_json(out / "local.json", local)
    write_json(out / "manifest.json", {"prepared_utc": now(), "source": source,
               "protocol_sha256": sha(out / "protocol.json"), "python": legacy.python_runtime(),
               "reference_runtime": runtime, "numeric_environment": NUMERIC_ENV,
               "full_experiment_authorized": p["study_kind"] == "main" and args.allow_full_experiment,
               "note": "Development smoke data are not main-study evidence. No original Metacat source is distributed here."})
    print(json.dumps({"prepared": str(out), "kind": p["study_kind"], "maximum_episodes": len(p["problems"]) * (
        p["construction"]["max_episodes"] + p["validation_episodes"] + p["port_episodes"])}), flush=True)


def verify_study(out, runtime=True):
    manifest, p, local = (read_json(out / name) for name in ("manifest.json", "protocol.json", "local.json"))
    validate_protocol(p)
    if sha(out / "protocol.json") != manifest["protocol_sha256"] or source_snapshot() != manifest["source"]:
        raise ValueError("Study inputs changed after preparation; preserve output and prepare a new version")
    if legacy.python_runtime() != manifest["python"]:
        raise ValueError("Python runtime changed after preparation")
    if p["study_kind"] == "main" and not manifest["full_experiment_authorized"]:
        raise ValueError("Main study was not explicitly authorized during preparation")
    if runtime:
        legacy.verify_reconstruction(local)
        if legacy.runtime_snapshot(local) != manifest["reference_runtime"]:
            raise ValueError("Scheme runtime changed after preparation")
    return manifest, p, local


def read_phase(out, p, phase, problem_index):
    count = p["construction"]["max_episodes"] if phase == "construction" else p[f"{phase}_episodes"]
    result, missing = [], False
    for i in range(count):
        row = load_completed(out, task_for(p, phase, problem_index, i))
        if row is None:
            missing = True
        elif missing:
            raise ValueError("Completed episodes have a gap; resume collection before analyzing")
        else:
            result.append(row)
    return result


def analyze(out):
    p = read_json(out / "protocol.json")
    validate_protocol(p)
    manifest = read_json(out / "manifest.json")
    if sha(out / "protocol.json") != manifest["protocol_sha256"]:
        raise ValueError("Changed archived protocol")
    results, totals = [], {"episodes": 0, "attempted_inner_runs": 0, "engine_error_episodes": 0, "capped_inner_runs": 0}
    for pi, problem in enumerate(p["problems"]):
        phases = {phase: read_phase(out, p, phase, pi) for phase in ("construction", "validation", "port")}
        ref = phases["construction"]
        history, stop_n = stopping_history(ref, p["construction"])
        if stop_n is not None and len(ref) != stop_n:
            raise ValueError("Construction continued after its declared stopping checkpoint")
        reason = "heuristic-target" if stop_n is not None else (
            "budget-exhausted" if len(ref) == p["construction"]["max_episodes"] else "incomplete")
        for rows in phases.values():
            totals["episodes"] += len(rows)
            totals["attempted_inner_runs"] += sum(r["attempted_runs"] for r in rows)
            totals["engine_error_episodes"] += sum(r["status"] == "engine-error" for r in rows)
            totals["capped_inner_runs"] += sum(r["capped_runs"] for r in rows)
        results.append({"problem": problem["name"], "construction_stop_reason": reason,
            "checkpoints": history, "phase_counts": {name: len(rows) for name, rows in phases.items()},
            "populations": {projection: {"reference": population(ref, projection),
                "validation": compare(ref, phases["validation"], projection),
                "port": compare(ref, phases["port"], projection)} for projection in PROJECTIONS}})
    complete = all(r["construction_stop_reason"] != "incomplete"
                   and r["phase_counts"]["validation"] == p["validation_episodes"]
                   and r["phase_counts"]["port"] == p["port_episodes"] for r in results)
    analysis = {"study_id": p["study_id"], "study_kind": p["study_kind"], "complete": complete,
                "totals": totals, "results": results,
                "interpretation": "f1/N is a heuristic missing-mass estimate for entire unordered best-answer sets, not a confidence bound or a per-member discovery probability. The two projections are paired, not independent."}
    write_json(out / "analysis.json", analysis)
    lines = [f"# {p['study_id']} Results", "", analysis["interpretation"], "",
             f"Complete: {complete}. Episodes: {totals['episodes']}. Inner runs: {totals['attempted_inner_runs']}.",
             f"Engine-error episodes: {totals['engine_error_episodes']}. Capped inner runs: {totals['capped_inner_runs']}.", "",
             "| Problem | Projection | N | f1 | f1/N | Stop | Held-out novel sets | Port novel sets |", "| --- | --- | ---: | ---: | ---: | --- | ---: | ---: |"]
    for r in results:
        for projection, data in r["populations"].items():
            ref = data["reference"]
            lines.append(f"| {r['problem']} | {projection} | {ref['N']} | {ref['f1']} | {ref['f1_over_N']} | {r['construction_stop_reason']} | {data['validation']['novel_outcome_episodes']} | {data['port']['novel_outcome_episodes']} |")
    lines.extend(["", "A completed smoke test establishes harness operation, not oracle completeness or port equivalence.",
                  "Budget exhaustion is not threshold attainment. Missing-p50 results for tiny checks are descriptive, not calibrated failures.", ""])
    (out / "REPORT.md").write_text("\n".join(lines))
    return analysis


def run(args):
    out = args.out.resolve()
    with locked(out):
        manifest, p, local = verify_study(out)
        authorize_main(p, args.allow_full_experiment)
        if (out / "COMPLETE.json").exists():
            print(json.dumps({"already_complete": True, "totals": analyze(out)["totals"]}), flush=True)
            return
        deadline = time.monotonic() + p["invocation_timeout_seconds"]
        progress = {"state": "running", "started_utc": now(), "completed_this_invocation": 0}
        write_json(out / "progress.json", progress)

        def execute(task):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("Invocation time budget exhausted")
            return execute_task(out, task, local, manifest, min(remaining, p["episode_timeout_seconds"]), args.retry_incomplete)

        try:
            with ThreadPoolExecutor(max_workers=p["workers"]) as pool:
                def batch(tasks):
                    pending = {pool.submit(execute, t): t for t in tasks}
                    try:
                        while pending:
                            done, _ = wait(pending, return_when=FIRST_COMPLETED)
                            for future in done:
                                task = pending.pop(future)
                                future.result()
                                progress.update(completed_this_invocation=progress["completed_this_invocation"] + 1,
                                                updated_utc=now(), phase=task["phase"], problem=task["problem"], episode=task["episode"])
                                write_json(out / "progress.json", progress)
                                print(json.dumps(progress), flush=True)
                    except BaseException:
                        for future in pending:
                            future.cancel()
                        raise

                config = p["construction"]
                for n in range(config["checkpoint_every"], config["max_episodes"] + 1, config["checkpoint_every"]):
                    tasks = []
                    for pi in range(len(p["problems"])):
                        # A resumed partial batch may have gaps; load each assigned receipt.
                        prefix = []
                        for i in range(config["max_episodes"]):
                            row = load_completed(out, task_for(p, "construction", pi, i))
                            if row is None:
                                break
                            prefix.append(row)
                        _, stop_n = stopping_history(prefix, config)
                        if stop_n is None:
                            tasks.extend(task_for(p, "construction", pi, i) for i in range(n)
                                         if load_completed(out, task_for(p, "construction", pi, i)) is None)
                    batch(tasks)
                for phase in ("validation", "port"):
                    batch([task_for(p, phase, pi, i) for pi in range(len(p["problems"]))
                           for i in range(p[f"{phase}_episodes"])
                           if load_completed(out, task_for(p, phase, pi, i)) is None])
            result = analyze(out)
            if not result["complete"]:
                raise ValueError("Coordinator finished without the declared observations")
            write_json(out / "COMPLETE.json", {"finished_utc": now(), "totals": result["totals"],
                       "analysis_sha256": sha(out / "analysis.json"), "protocol_sha256": sha(out / "protocol.json")})
            progress.update(state="complete", updated_utc=now(), totals=result["totals"])
        except BaseException as exc:
            progress.update(state="failed", updated_utc=now(), error_type=type(exc).__name__, error=str(exc))
            write_json(out / "progress.json", progress)
            raise
        write_json(out / "progress.json", progress)
        print(json.dumps(progress), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    prep = sub.add_parser("prepare")
    prep.add_argument("--protocol", type=Path, default=HERE / "protocol.smoke.json")
    prep.add_argument("--out", type=Path, required=True)
    prep.add_argument("--image", default="metacat:local")
    prep.add_argument("--allow-full-experiment", action="store_true")
    go = sub.add_parser("run")
    go.add_argument("--out", type=Path, required=True)
    go.add_argument("--allow-full-experiment", action="store_true")
    go.add_argument("--retry-incomplete", action="store_true")
    for name in ("analyze", "status"):
        p = sub.add_parser(name)
        p.add_argument("--out", type=Path, required=True)
    worker = sub.add_parser("worker")
    worker.add_argument("--task", type=Path, required=True)
    worker.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "prepare":
        prepare(args)
    elif args.command == "run":
        run(args)
    elif args.command == "analyze":
        print(json.dumps(analyze(args.out), indent=2))
    elif args.command == "status":
        print(json.dumps(read_json(args.out / "progress.json"), indent=2))
    else:
        return petacat_worker(args.task, args.output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
