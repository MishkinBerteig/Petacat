#!/usr/bin/env python3
"""Bounded reference-only pilot for individual episodic best-answer discovery."""

import argparse
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
import csv
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import shutil
from string import Template
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
from answers import DEFINITIONS, discovery_curve, select_answer

SPEC = importlib.util.spec_from_file_location("episodic_v1", HERE.parent / "episodic-v1/collect.py")
v1 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(v1)
read_json, write_json, sha, now = v1.read_json, v1.write_json, v1.sha, v1.now


def validate_protocol(p):
    if (p.get("schema_version") != 2 or p.get("study_kind") != "reference-discovery-pilot"
            or p.get("population") != "individual-best-answer-conditional-on-answered-episode"
            or p.get("definitions") != DEFINITIONS or p.get("stop_at_threshold") is not False
            or p.get("tie_policy") != "earliest-winning-occurrence-v1"):
        raise ValueError("Unsupported discovery-pilot population or tie policy")
    limits = {"episode_runs": 8, "episodes_per_problem": 1000, "checkpoint_every": 100,
              "max_codelets": 100000, "workers": 12, "episode_timeout_seconds": 300,
              "invocation_timeout_seconds": 14400}
    if any(type(p[k]) is not int or not 0 < p[k] <= limit for k, limit in limits.items()):
        raise ValueError("Pilot exceeds the authorized hard limits")
    if (p["episode_runs"] != 8 or p["episodes_per_problem"] % p["checkpoint_every"]
            or not isinstance(p["singleton_threshold"], (int, float))
            or not 0 < p["singleton_threshold"] < 1):
        raise ValueError("Invalid horizon, checkpoint schedule, or target")
    problems = p["problems"]
    if not 1 <= len(problems) <= 4 or len({x["name"] for x in problems}) != len(problems):
        raise ValueError("Pilot requires one to four unique problems")
    if type(p["seed_base"]) is not int or type(p["seed_stride"]) is not int:
        raise ValueError("Seed allocations must be integers")
    width = p["episodes_per_problem"] * p["episode_runs"]
    if (p["seed_stride"] < width or p["seed_base"] <= 0
            or p["seed_base"] + (len(problems) - 1) * p["seed_stride"] + width > 2**32):
        raise ValueError("Overlapping or invalid seed blocks")
    for x in problems:
        if (not re.fullmatch(r"[a-zA-Z0-9.-]+", x["name"]) or len(x["strings"]) != 3
                or not all(re.fullmatch(r"[a-z]+", s) for s in x["strings"])):
            raise ValueError("Invalid problem identifier or strings")


def snapshot():
    value = v1.source_snapshot()
    value["files"].update({str(p.relative_to(ROOT)): sha(p) for p in HERE.iterdir()
                           if p.is_file() and p.name != ".DS_Store"})
    return value


def task_for(p, pi, episode):
    problem = p["problems"][pi]
    return {"phase": "discovery", "engine": "metacat", "problem": problem["name"],
            "strings": problem["strings"], "episode": episode, "episode_runs": p["episode_runs"],
            "first_seed": p["seed_base"] + pi * p["seed_stride"] + episode * p["episode_runs"],
            "max_codelets": p["max_codelets"]}


def validate_row(row, task):
    v1.validate_row({k: v for k, v in row.items() if k != "best_answers"}, task)
    if set(row.get("best_answers", {})) != set(DEFINITIONS):
        raise ValueError("Missing earliest-winner evidence")
    for definition, projection in DEFINITIONS.items():
        selected = row["best_answers"][definition]
        candidates = row["outcomes"][projection].get("answers", [])
        if selected is None:
            if candidates:
                raise ValueError("Answered episode has no selected best answer")
        elif not candidates or selected not in candidates:
            raise ValueError("Selected answer is not a native co-winner")


def load_completed(out, task):
    row = v1.load_completed(out, task)
    if row is None:
        return None
    directory = v1.directory_for(out, task)
    receipt = read_json(directory / "complete.json")
    if "selection.json" not in receipt["files"]:
        raise ValueError("Unchecksummed winner selection")
    row["best_answers"] = read_json(directory / receipt["attempt"] / "selection.json")
    validate_row(row, task)
    return row


def execute_task(out, task, local, timeout, retry=False):
    existing = load_completed(out, task)
    if existing is not None:
        return existing
    directory = v1.directory_for(out, task)
    directory.mkdir(parents=True, exist_ok=True)
    prior = sorted(directory.glob("attempt-*"))
    if prior and not retry:
        raise ValueError("Incomplete attempt exists; review before --retry-incomplete")
    attempt = directory / f"attempt-{len(prior) + 1:03d}"
    attempt.mkdir()
    write_json(attempt / "task.json", task)
    metadata = {"task": task, "started_utc": now()}
    write_json(attempt / "attempt.json", metadata)
    name = "episodic-v2-" + hashlib.sha256(str(attempt).encode()).hexdigest()[:20]
    started = time.monotonic()
    try:
        (attempt / "collector.ss").write_text(Template((HERE / "collector.ss.in").read_text()).substitute(
            episode_runs=task["episode_runs"], first_seed=task["first_seed"], cap=task["max_codelets"],
            initial=task["strings"][0], modified=task["strings"][1], target=task["strings"][2]))
        command = [*v1.legacy.docker_base(local), "--name", name,
                   "-v", f"{local['source']}:/metacat:ro", "-v", f"{HERE}:/study:ro",
                   "-v", f"{v1.HERE}:/selectors:ro", "-v", f"{attempt}:/out", "-w", "/metacat",
                   "--entrypoint", "env", local["image"], "-u", "DISPLAY",
                   "scheme", "-q", "--script", "/out/collector.ss"]
        with (attempt / "stdout.log").open("w") as stdout, (attempt / "stderr.log").open("w") as stderr:
            result = subprocess.run(command, stdout=stdout, stderr=stderr, timeout=timeout)
        if result.returncode not in (0, 86):
            raise RuntimeError(f"Unclassified execution exit {result.returncode}")
        row = v1.scheme_row(attempt, task)
        row["elapsed_seconds"] = time.monotonic() - started
        v1.validate_row(row, task)
        if (result.returncode == 86) != (row["status"] == "engine-error"):
            raise ValueError("Exit and episode status disagree")
        if row["status"] == "engine-error":
            selected = dict.fromkeys(DEFINITIONS)
        else:
            with (attempt / "best.tsv").open(newline="") as stream:
                lines = list(csv.reader(stream, delimiter="\t"))
            if (len(lines) != 2 or any(len(line) != 2 for line in lines)
                    or {line[0] for line in lines} != set(DEFINITIONS)):
                raise ValueError("Invalid native earliest-winner record")
            selected = {definition: None if answer == "*NONE*" else answer for definition, answer in lines}
        validate_row(dict(row, best_answers=selected), task)
        write_json(attempt / "episode.json", row)
        write_json(attempt / "selection.json", selected)
        metadata.update(finished_utc=now(), exit_status=result.returncode, admitted=True)
        write_json(attempt / "attempt.json", metadata)
        write_json(directory / "complete.json", {"task": task, "attempt": attempt.name,
                   "files": {p.name: sha(p) for p in sorted(attempt.iterdir()) if p.is_file()}})
        return dict(row, best_answers=selected)
    except BaseException as exc:
        try:
            subprocess.run([local["docker"], "stop", "-t", "2", name], capture_output=True, timeout=30)
        except Exception as cleanup:
            metadata["cleanup_error"] = str(cleanup)
        metadata.update(finished_utc=now(), admitted=False, error_type=type(exc).__name__, error=str(exc))
        write_json(attempt / "attempt.json", metadata)
        raise


def prepare(args):
    p = read_json(args.protocol)
    validate_protocol(p)
    out = args.out.resolve()
    if out.exists():
        raise ValueError("Refusing to overwrite an existing pilot")
    docker = shutil.which("docker")
    if not docker:
        raise ValueError("Docker is required on PATH")
    local = {"docker": docker, "image": v1.capture([docker, "image", "inspect", args.image, "--format", "{{.Id}}"]),
             "source": str((ROOT / "Metacat/build/source").resolve())}
    v1.legacy.verify_reconstruction(local)
    manifest = {"prepared_utc": now(), "source": snapshot(), "python": v1.legacy.python_runtime(),
                "reference_runtime": v1.legacy.runtime_snapshot(local), "full_experiment_authorized": False,
                "note": "Reference-only discovery pilot, not a saturated oracle or a port comparison."}
    out.mkdir(parents=True)
    write_json(out / "protocol.json", p)
    write_json(out / "local.json", local)
    manifest["protocol_sha256"] = sha(out / "protocol.json")
    write_json(out / "manifest.json", manifest)
    print(json.dumps({"prepared": True, "maximum_episodes": len(p["problems"]) * p["episodes_per_problem"],
                      "maximum_inner_runs": len(p["problems"]) * p["episodes_per_problem"] * p["episode_runs"]}), flush=True)


def verify_study(out):
    p, m, local = (read_json(out / f"{name}.json") for name in ("protocol", "manifest", "local"))
    validate_protocol(p)
    if sha(out / "protocol.json") != m["protocol_sha256"] or snapshot() != m["source"]:
        raise ValueError("Pilot inputs changed; preserve output and use a new version")
    if v1.legacy.python_runtime() != m["python"]:
        raise ValueError("Python runtime changed")
    v1.legacy.verify_reconstruction(local)
    if v1.legacy.runtime_snapshot(local) != m["reference_runtime"]:
        raise ValueError("Reference runtime changed")
    return p, m, local


def load_rows(out, p):
    rows = []
    for pi in range(len(p["problems"])):
        for episode in range(p["episodes_per_problem"]):
            row = load_completed(out, task_for(p, pi, episode))
            if row is not None:
                rows.append(row)
    return rows


def summarize(rows, p):
    grouped = {x["name"]: {} for x in p["problems"]}
    indices = {x["name"]: i for i, x in enumerate(p["problems"])}
    for row in rows:
        task = row["task"]
        name, episode = task["problem"], task["episode"]
        if (name not in grouped or type(episode) is not int or not 0 <= episode < p["episodes_per_problem"]
                or episode in grouped[name]):
            raise ValueError("Duplicate or invalid episode")
        validate_row(row, task_for(p, indices[name], episode))
        grouped[name][episode] = row
    results = []
    for name, episodes in grouped.items():
        # Parallel completion order never determines the statistical prefix.
        prefix = []
        while len(prefix) in episodes:
            prefix.append(episodes[len(prefix)])
        results.append({"problem": name, "completed_episodes": len(episodes), "contiguous_episodes": len(prefix),
                        "definitions": {d: discovery_curve(prefix, d, p) for d in DEFINITIONS}})
    totals = {"completed_episodes": len(rows), "attempted_inner_runs": sum(r["attempted_runs"] for r in rows),
              "codelets": sum(r["codelets"] for r in rows),
              "answer_runs": sum(r["answer_runs"] for r in rows),
              "answerless_runs": sum(r["answerless_runs"] for r in rows),
              "capped_runs": sum(r["capped_runs"] for r in rows),
              "engine_error_episodes": sum(r["status"] == "engine-error" for r in rows),
              "summed_episode_wall_seconds": sum(r["elapsed_seconds"] for r in rows)}
    return {"study_id": p["study_id"], "complete": all(r["contiguous_episodes"] == p["episodes_per_problem"] for r in results),
            "totals": totals, "results": results,
            "interpretation": "Separate individual-answer populations. N counts answered complete episodes; failures and answerless episodes are reported separately. f1/N is a heuristic conditional missing-mass estimate, not a confidence bound. Pilot collection never stops on a threshold crossing."}


def write_reports(out, result, p):
    write_json(out / "analysis.json", result)
    fields = ["problem", "definition", "episodes", "N", "f1", "f1_over_N", "distinct_answers",
              "tied_answer_episodes", "engine_error_episodes", "answerless_episodes", "at_or_below_target"]
    with (out / "curves.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for r in result["results"]:
            for definition, data in r["definitions"].items():
                for point in data["checkpoints"]:
                    writer.writerow({f: r["problem"] if f == "problem" else definition if f == "definition"
                                     else point[f] for f in fields})
    lines = [f"# {p['study_id']}", "", result["interpretation"], "",
             f"Complete: {result['complete']}. Episodes: {result['totals']['completed_episodes']}. Inner runs: {result['totals']['attempted_inner_runs']}.",
             "", "| Problem | Definition | Episodes | N answers | f1 | f1/N | Distinct answers |",
             "| --- | --- | ---: | ---: | ---: | ---: | ---: |"]
    for r in result["results"]:
        for definition, data in r["definitions"].items():
            for point in data["checkpoints"]:
                lines.append(f"| {r['problem']} | {definition} | {point['episodes']} | {point['N']} | {point['f1']} | {point['f1_over_N']} | {point['distinct_answers']} |")
    lines += ["", "The target is 0.0001; with N <= 1000 any nonzero f1/N is at least 0.001.",
              "A zero value or early target crossing is not evidence that discovery probability is zero or below 0.0001.",
              "Compare actual inner-run costs (eight per full episode), not episode counts alone.", ""]
    (out / "REPORT.md").write_text("\n".join(lines))


def analyze(out):
    p = read_json(out / "protocol.json")
    validate_protocol(p)
    if sha(out / "protocol.json") != read_json(out / "manifest.json")["protocol_sha256"]:
        raise ValueError("Changed archived protocol")
    result = summarize(load_rows(out, p), p)
    write_reports(out, result, p)
    return result


def import_completed(out, parent):
    """Explicit serializer-only amendment; preserve the complete interrupted parent."""
    p, manifest, _ = verify_study(out)
    if (out / "episodes").exists() or (out / "parent-import.json").exists():
        raise ValueError("Import requires an empty prepared pilot")
    parent_manifest = read_json(parent / "manifest.json")
    if (read_json(parent / "protocol.json") != p
            or sha(parent / "protocol.json") != parent_manifest["protocol_sha256"]
            or parent_manifest["python"] != manifest["python"]
            or parent_manifest["reference_runtime"] != manifest["reference_runtime"]):
        raise ValueError("Parent protocol or runtime differs")
    old, new = parent_manifest["source"]["files"], manifest["source"]["files"]
    changed = {name for name in old.keys() | new.keys() if old.get(name) != new.get(name)}
    allowed = {f"studies/episodic-v2/{name}" for name in
               ("selection.ss", "fixtures.ss", "pilot.py", "test_pilot.py", "README.md")}
    if not changed <= allowed or parent_manifest["source"]["git_commit"] != manifest["source"]["git_commit"]:
        raise ValueError("Import is limited to the documented serializer-only correction")
    parent_hashes = {str(path.relative_to(parent)): sha(path) for path in parent.rglob("*") if path.is_file()}
    rows = load_rows(parent, p)
    incomplete = []
    for path in sorted(parent.glob("episodes/*/*/*/attempt-*/attempt.json")):
        metadata = read_json(path)
        if not metadata.get("admitted"):
            with path.with_name("raw.tsv").open(newline="") as stream:
                header = next(csv.reader(stream, delimiter="\t"))
            if len(header) != 8 or header[:2] != ["EP", "complete"]:
                raise ValueError("Interrupted attempt has no complete search accounting")
            incomplete.append({"task": metadata["task"], "attempted_inner_runs": int(header[2]),
                               "codelets": int(header[6]), "admitted": False})
    shutil.copytree(parent, out / "interrupted-parent")
    for row in rows:
        source = v1.directory_for(parent, row["task"])
        destination = v1.directory_for(out, row["task"])
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source, destination)
    copied_hashes = {str(path.relative_to(out / "interrupted-parent")): sha(path)
                     for path in (out / "interrupted-parent").rglob("*") if path.is_file()}
    if copied_hashes != parent_hashes:
        raise ValueError("Parent archive changed during import")
    write_json(out / "parent-import.json", {"reason": "Serializer called native diff (#f) as a slipnode; no search or selection semantics changed.",
        "parent_manifest_sha256": sha(parent / "manifest.json"), "parent_files": parent_hashes,
        "changed_source_files": sorted(changed), "inherited_completed_episodes": len(rows),
        "incomplete_attempts": incomplete,
        "excluded_diagnostic_inner_runs": sum(x["attempted_inner_runs"] for x in incomplete),
        "excluded_diagnostic_codelets": sum(x["codelets"] for x in incomplete)})
    print(json.dumps({"inherited_episodes": len(rows), "incomplete_attempts_to_replay": len(incomplete)}), flush=True)


def run(args):
    out = args.out.resolve()
    with v1.locked(out):
        p, manifest, local = verify_study(out)
        if (out / "COMPLETE.json").exists():
            print(json.dumps({"already_complete": True, "totals": analyze(out)["totals"]}), flush=True)
            return
        deadline = time.monotonic() + p["invocation_timeout_seconds"]
        saved = {(r["task"]["problem"], r["task"]["episode"]): r for r in load_rows(out, p)}
        progress = {"state": "running", "started_utc": now(), "completed_episodes": len(saved),
                    "maximum_episodes": len(p["problems"]) * p["episodes_per_problem"]}
        write_json(out / "progress.json", progress)

        def execute(task):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("Pilot invocation budget exhausted")
            return execute_task(out, task, local, min(remaining, p["episode_timeout_seconds"]), args.retry_incomplete)

        try:
            with ThreadPoolExecutor(max_workers=p["workers"]) as pool:
                for checkpoint in range(p["checkpoint_every"], p["episodes_per_problem"] + 1, p["checkpoint_every"]):
                    assignments = iter(task_for(p, pi, i) for i in range(checkpoint)
                                       for pi, problem in enumerate(p["problems"])
                                       if (problem["name"], i) not in saved)
                    pending = {}

                    def fill():
                        while len(pending) < p["workers"]:
                            task = next(assignments, None)
                            if task is None:
                                break
                            pending[pool.submit(execute, task)] = task

                    fill()
                    try:
                        while pending:
                            done, _ = wait(pending, return_when=FIRST_COMPLETED)
                            for future in done:
                                task = pending.pop(future)
                                saved[task["problem"], task["episode"]] = future.result()
                            progress.update(completed_episodes=len(saved), updated_utc=now(), checkpoint=checkpoint)
                            write_json(out / "progress.json", progress)
                            fill()
                    except BaseException:
                        for future in pending:
                            future.cancel()
                        raise
                    result = summarize(list(saved.values()), p)
                    write_reports(out, result, p)
                    print(json.dumps({"checkpoint": checkpoint, "totals": result["totals"],
                        "curves": {r["problem"]: {d: {k: data["latest"][k] for k in ("N", "f1", "f1_over_N", "distinct_answers")}
                                   for d, data in r["definitions"].items()} for r in result["results"]}}), flush=True)
            result = analyze(out)
            if not result["complete"]:
                raise ValueError("Pilot finished without all declared episodes")
            write_json(out / "COMPLETE.json", {"finished_utc": now(), "totals": result["totals"],
                       "analysis_sha256": sha(out / "analysis.json"), "protocol_sha256": sha(out / "protocol.json")})
            progress.update(state="complete", updated_utc=now(), totals=result["totals"])
        except BaseException as exc:
            progress.update(state="failed", updated_utc=now(), error_type=type(exc).__name__, error=str(exc))
            write_json(out / "progress.json", progress)
            raise
        write_json(out / "progress.json", progress)
        print(json.dumps(progress), flush=True)


def export(out, destination):
    if destination.exists():
        raise ValueError("Refusing to overwrite a public export")
    result = analyze(out)
    if not result["complete"] or not (out / "COMPLETE.json").exists():
        raise ValueError("Only complete pilots may be exported")
    p = read_json(out / "protocol.json")
    data = {name: (out / name).read_bytes() for name in
            ("protocol.json", "manifest.json", "analysis.json", "curves.csv", "REPORT.md", "COMPLETE.json")}
    if (out / "parent-import.json").exists():
        data["parent-import.json"] = (out / "parent-import.json").read_bytes()
    data["episodes.json"] = (json.dumps(load_rows(out, p), indent=2, sort_keys=True) + "\n").encode()
    # Public allowlist intentionally omits local.json, attempts, and operational logs.
    if any(token in body for token in (b"/Users/", b"/home/", b"HostName", b"sha256:") for body in data.values()):
        raise ValueError("Review possible private execution metadata before export")
    destination.mkdir(parents=True)
    for name, body in data.items():
        (destination / name).write_bytes(body)
    write_json(destination / "SHA256.json", {name: sha(destination / name) for name in sorted(data)})
    print(json.dumps({"exported_episodes": result["totals"]["completed_episodes"]}), flush=True)


def verify_export(directory):
    expected = {"protocol.json", "manifest.json", "analysis.json", "curves.csv", "REPORT.md", "COMPLETE.json", "episodes.json"}
    if (directory / "parent-import.json").exists():
        expected.add("parent-import.json")
    checksums = read_json(directory / "SHA256.json")
    if set(checksums) != expected or any(sha(directory / name) != digest for name, digest in checksums.items()):
        raise ValueError("Public bundle checksum mismatch")
    p, manifest = (read_json(directory / f"{name}.json") for name in ("protocol", "manifest"))
    validate_protocol(p)
    if sha(directory / "protocol.json") != manifest["protocol_sha256"]:
        raise ValueError("Protocol receipt mismatch")
    for name in ("answers.py", "pilot.py"):
        if sha(HERE / name) != manifest["source"]["files"][f"studies/episodic-v2/{name}"]:
            raise ValueError("Use the recorded analysis tool version")
    recorded = read_json(directory / "analysis.json")
    result = summarize(read_json(directory / "episodes.json"), p)
    complete = read_json(directory / "COMPLETE.json")
    if (result != recorded or not result["complete"] or complete["totals"] != result["totals"]
            or complete["analysis_sha256"] != sha(directory / "analysis.json")
            or complete["protocol_sha256"] != manifest["protocol_sha256"]):
        raise ValueError("Recomputed pilot differs from archived results")
    print(f"PASS: {result['totals']['completed_episodes']} episodes; all curves reproduced; zero engine executions")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("prepare", "run", "analyze", "status", "export", "import-completed"):
        cmd = sub.add_parser(name)
        cmd.add_argument("--out", type=Path, required=True)
        if name == "prepare":
            cmd.add_argument("--protocol", type=Path, default=HERE / "protocol.pilot.json")
            cmd.add_argument("--image", default="metacat:local")
        if name == "run":
            cmd.add_argument("--retry-incomplete", action="store_true")
        if name == "export":
            cmd.add_argument("--destination", type=Path, required=True)
        if name == "import-completed":
            cmd.add_argument("--parent", type=Path, required=True)
    sub.add_parser("verify-export").add_argument("directory", type=Path)
    args = parser.parse_args()
    if args.command == "prepare":
        prepare(args)
    elif args.command == "run":
        run(args)
    elif args.command == "analyze":
        print(json.dumps(analyze(args.out), indent=2))
    elif args.command == "status":
        print(json.dumps(read_json(args.out / "progress.json"), indent=2))
    elif args.command == "export":
        export(args.out, args.destination)
    elif args.command == "import-completed":
        import_completed(args.out, args.parent)
    else:
        verify_export(args.directory)


if __name__ == "__main__":
    main()
