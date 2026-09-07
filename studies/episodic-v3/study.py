#!/usr/bin/env python3
"""Capped construction, gated frozen-oracle validation, and descriptive port checks."""

import argparse
from collections import deque
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from copy import deepcopy
import csv
import importlib.util
import json
import os
from pathlib import Path
import random
import shutil
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
from analysis_tools import Construction, DEFINITIONS, frequencies, membership, population, validate_frozen

sys.path.insert(0, str(HERE.parent / "episodic-v2"))
SPEC = importlib.util.spec_from_file_location("episodic_v2", HERE.parent / "episodic-v2/pilot.py")
v2 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(v2)
v1 = v2.v1
read_json, write_json, sha, now = v1.read_json, v1.write_json, v1.sha, v1.now
PHASES = ("construction", "validation", "port")


def validate_protocol(p):
    if (p.get("schema_version") != 3 or p.get("study_kind") not in ("main", "smoke")
            or p.get("population") != "individual-best-answer-conditional-on-answered-episode"
            or p.get("definitions") != DEFINITIONS or p.get("tie_policy") != "earliest-winning-occurrence-v1"
            or p.get("episode_runs") != 8 or p.get("max_codelets") != 100000 or p.get("backend") != "numpy"
            or p.get("sampling") != "independent-uniform-first-seeds-with-replacement"
            or p.get("port_frequency_inference") != "descriptive-only"
            or p.get("pilot_reuse") != "all-recorded-pilot-episodes-as-construction-prefix-no-retrospective-freezing"):
        raise ValueError("Unsupported study identity or execution policy")
    c, v = p["construction"], p["validation"]
    if (c["min_episodes"] != 1 or c["checkpoint_every"] != 1
            or not 0 < c["singleton_threshold"] < 1 or type(c["max_episodes"]) is not int
            or not 1 <= c["max_episodes"] <= 2000
            or v["requires_both_thresholds"] is not True or v["fixed_sample_size"] is not True
            or v["method"] != "one-sided-exact-binomial-bonferroni"
            or v["missing_mass_target"] != .01 or v["family_alpha"] != .05):
        raise ValueError("Invalid stopping or qualification policy")
    limits = {"workers": 12, "episode_timeout_seconds": 300,
              "invocation_timeout_seconds": 43200, "port_episodes": 100}
    if any(type(p[k]) is not int or not 1 <= p[k] <= maximum for k, maximum in limits.items()):
        raise ValueError("Study exceeds an authorized budget")
    if type(v["episodes"]) is not int or not 1 <= v["episodes"] <= 1000:
        raise ValueError("Invalid validation budget")
    canonical = read_json(HERE.parent / "support-v1/protocol.json")["problems"]
    if (not p["problems"] or len({x["name"] for x in p["problems"]}) != len(p["problems"])
            or any(x not in canonical for x in p["problems"])
            or v["family_size"] != 2 * len(p["problems"])):
        raise ValueError("Problem list or simultaneous-confidence family changed")
    if p["study_kind"] == "main":
        if (p["problems"] != canonical or c["max_episodes"] != 2000 or c["singleton_threshold"] != .0001
                or v["episodes"] != 1000 or p["port_episodes"] != 100):
            raise ValueError("Main protocol differs from the authorized 19-problem study")
    elif (len(p["problems"]) > 4 or c["max_episodes"] > 4 or c["singleton_threshold"] < .1
          or v["episodes"] > 2 or p["port_episodes"] > 2 or p["workers"] > 2
          or p["invocation_timeout_seconds"] > 1800):
        raise ValueError("Smoke exceeds its independent hard limits")


def authorize(p, allowed):
    if p["study_kind"] == "main" and not allowed:
        raise ValueError("Main collection requires --allow-full-experiment at prepare and run")


def snapshot():
    result = v2.snapshot()
    result["files"].update({str(f.relative_to(ROOT)): sha(f) for f in HERE.iterdir()
                            if f.is_file() and f.name != ".DS_Store"})
    return result


def phase_budget(p, phase):
    return p["construction"]["max_episodes"] if phase == "construction" else (
        p["validation"]["episodes"] if phase == "validation" else p["port_episodes"])


def generate_seeds(p):
    rng = random.SystemRandom()
    return {phase: {problem["name"]: [rng.randrange(1, 2**32 - 7)
                                     for _ in range(phase_budget(p, phase))]
                    for problem in p["problems"]} for phase in PHASES}


def task_for(p, seeds, phase, pi, episode):
    problem = p["problems"][pi]
    return {"phase": phase, "engine": "petacat" if phase == "port" else "metacat",
            "problem": problem["name"], "strings": problem["strings"], "episode": episode,
            "episode_runs": 8, "first_seed": seeds[phase][problem["name"]][episode], "max_codelets": 100000}


def validate_seeds(p, seeds):
    if set(seeds) != set(PHASES):
        raise ValueError("Incomplete phase seed plan")
    for phase in PHASES:
        if set(seeds[phase]) != {x["name"] for x in p["problems"]}:
            raise ValueError("Incomplete problem seed plan")
        for values in seeds[phase].values():
            if len(values) != phase_budget(p, phase) or any(type(s) is not int or not 1 <= s <= 2**32 - 8 for s in values):
                raise ValueError("Seed plan exceeds the episode domain or budget")


def save_import(out, row, task, source_receipt):
    directory = v1.directory_for(out, task)
    attempt = directory / "attempt-001"
    attempt.mkdir(parents=True)
    mapped = deepcopy(row)
    selected = mapped.pop("best_answers")
    mapped["task"] = task
    v2.validate_row(dict(mapped, best_answers=selected), task)
    for name, value in (("task.json", task), ("episode.json", mapped), ("selection.json", selected),
                        ("attempt.json", {"task": task, "admitted": True, "imported": True,
                                          "source_receipt": source_receipt})):
        write_json(attempt / name, value)
    write_json(directory / "complete.json", {"task": task, "attempt": attempt.name,
               "files": {f.name: sha(f) for f in sorted(attempt.iterdir())}})


def prepare(args):
    p = read_json(args.protocol)
    validate_protocol(p)
    authorize(p, args.allow_full_experiment)
    out = args.out.resolve()
    if out.exists():
        raise ValueError("Refusing to overwrite an existing study")
    docker = shutil.which("docker")
    if not docker:
        raise ValueError("Docker is required on PATH")
    local = {"docker": docker, "image": v1.capture([docker, "image", "inspect", args.image, "--format", "{{.Id}}"]),
             "source": str((ROOT / "Metacat/build/source").resolve())}
    v1.legacy.verify_reconstruction(local)
    source, runtime, python = snapshot(), v1.legacy.runtime_snapshot(local), v1.legacy.python_runtime()
    seeds = generate_seeds(p)
    parent_rows, parent_hashes = [], {}
    imported = {x["name"]: 0 for x in p["problems"]}
    if args.pilot:
        if p["study_kind"] != "main":
            raise ValueError("Pilot reuse is not permitted in a smoke test")
        parent = args.pilot.resolve()
        old = read_json(parent / "manifest.json")
        old_p = read_json(parent / "protocol.json")
        if (old["python"] != python or old["reference_runtime"] != runtime
                or any(source["files"].get(n) != h for n, h in old["source"]["files"].items())
                or not (parent / "COMPLETE.json").exists()
                or old["protocol_sha256"] != sha(parent / "protocol.json")
                or old_p["tie_policy"] != p["tie_policy"]):
            raise ValueError("Pilot source, protocol receipt, or runtime differs")
        parent_rows = v2.load_rows(parent, old_p)
        old_result = v2.summarize(parent_rows, old_p)
        if (not old_result["complete"] or old_result != read_json(parent / "analysis.json")
                or sha(parent / "analysis.json") != read_json(parent / "COMPLETE.json")["analysis_sha256"]):
            raise ValueError("Pilot is incomplete or changed")
        parent_hashes = {str(f.relative_to(parent)): sha(f) for f in parent.rglob("*") if f.is_file()}
        for row in parent_rows:
            name, index = row["task"]["problem"], row["task"]["episode"]
            canonical = next(x for x in p["problems"] if x["name"] == name)
            if canonical["strings"] != row["task"]["strings"] or index >= p["construction"]["max_episodes"]:
                raise ValueError("Imported episode falls outside the construction domain")
            seeds["construction"][name][index] = row["task"]["first_seed"]
            imported[name] += 1
    validate_seeds(p, seeds)
    out.mkdir(parents=True)
    write_json(out / "protocol.json", p)
    write_json(out / "seeds.json", seeds)
    write_json(out / "local.json", local)
    manifest = {"prepared_utc": now(), "source": source, "python": python, "reference_runtime": runtime,
                "numeric_environment": v1.NUMERIC_ENV, "protocol_sha256": sha(out / "protocol.json"),
                "seeds_sha256": sha(out / "seeds.json"), "imported_episodes": imported,
                "full_experiment_authorized": p["study_kind"] == "main" and args.allow_full_experiment,
                "note": "Pilot reuse and stopping policy are post-pilot decisions. No retrospective early-stop savings claimed."}
    if args.pilot:
        shutil.copytree(args.pilot, out / "preserved-pilot")
        copied = {str(f.relative_to(out / "preserved-pilot")): sha(f)
                  for f in (out / "preserved-pilot").rglob("*") if f.is_file()}
        if copied != parent_hashes:
            raise ValueError("Pilot changed while being preserved")
        for row in parent_rows:
            pi = next(i for i, x in enumerate(p["problems"]) if x["name"] == row["task"]["problem"])
            task = task_for(p, seeds, "construction", pi, row["task"]["episode"])
            receipt = str((v1.directory_for(Path("."), row["task"]) / "complete.json"))
            save_import(out, row, task, {"path": receipt, "sha256": parent_hashes[receipt]})
        overhead = read_json(args.pilot / "parent-import.json") if (args.pilot / "parent-import.json").exists() else {}
        write_json(out / "pilot-import.json", {"parent_files": parent_hashes,
                   "inherited_episodes": len(parent_rows),
                   "inherited_inner_runs": sum(r["attempted_runs"] for r in parent_rows),
                   "excluded_diagnostic_inner_runs": overhead.get("excluded_diagnostic_inner_runs", 0),
                   "excluded_diagnostic_codelets": overhead.get("excluded_diagnostic_codelets", 0),
                   "policy": p["pilot_reuse"]})
        manifest["pilot_import_sha256"] = sha(out / "pilot-import.json")
    write_json(out / "manifest.json", manifest)
    print(json.dumps({"prepared": True, "imported_episodes": sum(imported.values()),
                      "maximum_inner_runs_including_inherited": 8 * len(p["problems"]) * sum(phase_budget(p, ph) for ph in PHASES)}), flush=True)


def verify_study(out, runtime=True):
    p, m, seeds = (read_json(out / f"{name}.json") for name in ("protocol", "manifest", "seeds"))
    validate_protocol(p)
    validate_seeds(p, seeds)
    if sha(out / "protocol.json") != m["protocol_sha256"] or sha(out / "seeds.json") != m["seeds_sha256"]:
        raise ValueError("Prepared sampling plan changed")
    if m.get("pilot_import_sha256") and sha(out / "pilot-import.json") != m["pilot_import_sha256"]:
        raise ValueError("Pilot import provenance changed")
    if runtime:
        if snapshot() != m["source"] or v1.legacy.python_runtime() != m["python"]:
            raise ValueError("Frozen source or Python runtime changed")
        local = read_json(out / "local.json")
        v1.legacy.verify_reconstruction(local)
        if v1.legacy.runtime_snapshot(local) != m["reference_runtime"]:
            raise ValueError("Reference runtime changed")
    else:
        local = None
    return p, m, seeds, local


def port_selection(summaries, judge, reducer):
    outcomes, winners = reducer(summaries, judge)
    # Port memory appends, so summaries are oldest first before canonicalization.
    chosen = {d: next((a["answer"] for a in summaries if a in winners[projection]), None)
              for d, projection in DEFINITIONS.items()}
    return outcomes, winners, chosen


def port_worker(task_path, output):
    selected = dict.fromkeys(DEFINITIONS)
    original = v1.reduce_answers

    def reduce(summaries, judge):
        outcomes, winners, chosen = port_selection(summaries, judge, original)
        selected.update(chosen)
        return outcomes, winners

    v1.reduce_answers = reduce
    try:
        code = v1.petacat_worker(task_path, output)
    finally:
        v1.reduce_answers = original
    row = read_json(output)
    v2.validate_row(dict(row, best_answers=selected), read_json(task_path))
    write_json(output.with_name("selection.json"), selected)
    return code


def execute_task(out, task, local, timeout):
    existing = v2.load_completed(out, task)
    if existing is not None:
        return existing
    if task["engine"] == "metacat":
        return v2.execute_task(out, task, local, timeout)
    directory = v1.directory_for(out, task)
    if list(directory.glob("attempt-*")):
        raise ValueError("Incomplete port attempt requires review, not an automatic retry")
    attempt = directory / "attempt-001"
    attempt.mkdir(parents=True)
    write_json(attempt / "task.json", task)
    metadata = {"task": task, "started_utc": now()}
    write_json(attempt / "attempt.json", metadata)
    started = time.monotonic()
    try:
        command = [sys.executable, str(HERE / "study.py"), "worker", "--task", str(attempt / "task.json"),
                   "--output", str(attempt / "episode.json")]
        with (attempt / "stdout.log").open("w") as stdout, (attempt / "stderr.log").open("w") as stderr:
            result = subprocess.run(command, stdout=stdout, stderr=stderr, timeout=timeout,
                                    env=dict(os.environ, **v1.NUMERIC_ENV))
        if result.returncode not in (0, 86):
            raise RuntimeError(f"Unclassified port execution exit {result.returncode}")
        row = read_json(attempt / "episode.json")
        row["elapsed_seconds"] = time.monotonic() - started
        selected = read_json(attempt / "selection.json")
        v2.validate_row(dict(row, best_answers=selected), task)
        if (result.returncode == 86) != (row["status"] == "engine-error"):
            raise ValueError("Port exit and result disagree")
        write_json(attempt / "episode.json", row)
        metadata.update(finished_utc=now(), admitted=True, exit_status=result.returncode)
        write_json(attempt / "attempt.json", metadata)
        write_json(directory / "complete.json", {"task": task, "attempt": attempt.name,
                   "files": {f.name: sha(f) for f in sorted(attempt.iterdir()) if f.is_file()}})
        return dict(row, best_answers=selected)
    except BaseException as exc:
        metadata.update(finished_utc=now(), admitted=False, error_type=type(exc).__name__, error=str(exc))
        write_json(attempt / "attempt.json", metadata)
        raise


def load_rows(out, p, seeds):
    rows = []
    for phase in PHASES:
        for pi in range(len(p["problems"])):
            for episode in range(phase_budget(p, phase)):
                row = v2.load_completed(out, task_for(p, seeds, phase, pi, episode))
                if row is not None:
                    rows.append(row)
    return rows


def group_rows(rows, p, seeds):
    grouped = {x["name"]: {ph: {} for ph in PHASES} for x in p["problems"]}
    indices = {x["name"]: i for i, x in enumerate(p["problems"])}
    for row in rows:
        task = row["task"]
        name, phase, ep = task["problem"], task["phase"], task["episode"]
        if (name not in grouped or phase not in PHASES or type(ep) is not int
                or not 0 <= ep < phase_budget(p, phase) or ep in grouped[name][phase]):
            raise ValueError("Unknown, duplicate, or out-of-budget episode")
        v2.validate_row(row, task_for(p, seeds, phase, indices[name], ep))
        grouped[name][phase][ep] = row
    return grouped


def ordered(rows):
    if sorted(rows) != list(range(len(rows))):
        raise ValueError("Incomplete phase prefix; resume before final analysis")
    return [rows[i] for i in range(len(rows))]


def summarize(rows, p, seeds, imported):
    grouped = group_rows(rows, p, seeds)
    results = []
    for name, phases in grouped.items():
        ref, val, port = (ordered(phases[ph]) for ph in PHASES)
        construction = Construction(p["construction"], imported.get(name, 0))
        for row in ref:
            construction.add(row)
        if (val or port) and not construction.done:
            raise ValueError("Checks started before construction finished")
        data = {}
        for d in DEFINITIONS:
            full_ref, target = population(ref, d), population(port, d)
            frozen = construction.frozen[d]
            data[d] = {"reference_all_collected": full_ref, "port": target,
                       "frequency_comparison": frequencies(full_ref, target),
                       "frequency_inference": "descriptive-only; no p-values or equivalence claim",
                       "validation": validate_frozen(val, d, frozen, p["validation"], construction.qualified),
                       "port_membership": membership(port, d, frozen) if frozen else None}
        results.append({"problem": name, "construction": construction.summary(), "definitions": data,
                        "phase_episodes": {ph: len(v) for ph, v in phases.items()},
                        "coverage_qualified": construction.qualified and all(data[d]["validation"]["coverage_claim"] for d in DEFINITIONS)})
    fields = ("attempted_runs", "answer_runs", "answerless_runs", "capped_runs", "codelets", "elapsed_seconds")
    totals = {ph: {"episodes": sum(r["task"]["phase"] == ph for r in rows),
                  **{k: sum(r[k] for r in rows if r["task"]["phase"] == ph) for k in fields},
                  "engine_error_episodes": sum(r["status"] == "engine-error" and r["task"]["phase"] == ph for r in rows)}
              for ph in PHASES}
    complete = all(r["construction"]["stop_reason"] != "incomplete"
                   and r["phase_episodes"]["port"] == p["port_episodes"]
                   and r["phase_episodes"]["validation"] == (p["validation"]["episodes"] if r["construction"]["validation_eligible"] else 0)
                   for r in results)
    return {"study_id": p["study_id"], "complete": complete, "totals": totals, "results": results,
            "interpretation": "Per-episode Good-Turing stopping is heuristic. Validation is fixed-size and conditional on answered complete episodes, with 95% simultaneous bounds over the preregistered 38 populations in the main study. Capped problems retain descriptive reference/port frequencies without a coverage guarantee. No port equivalence or defect-detection power is claimed."}


def write_reports(out, analysis):
    write_json(out / "analysis.json", analysis)
    write_json(out / "oracles.json", {r["problem"]: r["construction"]["frozen"] for r in analysis["results"]})
    lines = [f"# {analysis['study_id']}", "", analysis["interpretation"], "",
             "| Problem | Construction episodes | Stop | A freeze | B freeze | Validation episodes | Port episodes | Coverage qualified |",
             "| --- | ---: | --- | ---: | ---: | ---: | ---: | --- |"]
    for r in analysis["results"]:
        c = r["construction"]
        a, b = ((c["frozen"][d] or {}).get("at_episode", "not met") for d in DEFINITIONS)
        lines.append(f"| {r['problem']} | {c['episodes']} | {c['stop_reason']} | {a} | {b} | {r['phase_episodes']['validation']} | {r['phase_episodes']['port']} | {r['coverage_qualified']} |")
    lines += ["", "## Validation Strength", "",
              "Bounds are conditional on answered, complete episodes. Errors and entirely answerless episodes are retained separately.",
              "A skipped validation has no statistical coverage guarantee; it does not make the retained observations invalid.", "",
              "| Problem | Definition | Status | Answered N | Outside occurrences | Adjusted upper bound |",
              "| --- | --- | --- | ---: | ---: | ---: |"]
    for r in analysis["results"]:
        for d, data in r["definitions"].items():
            v = data["validation"]
            lines.append(f"| {r['problem']} | {d} | {v['status']} | {v.get('N', 'not collected')} | {v.get('outside_occurrences', 'not collected')} | {v['upper_bound']} |")
    lines += ["", "All reference/port frequency tables are descriptive. Consult frequencies.csv and analysis.json; no frequency p-values, equivalence claims, or automatic bug verdicts are assigned.",
              "Frozen supports are recorded separately from the frequencies of all construction observations."]
    (out / "REPORT.md").write_text("\n".join(lines) + "\n")
    with (out / "curves.csv").open("w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["problem", "definition", "episodes", "N", "f1", "f1_over_N", "distinct_answers", "freeze_eligible", "frozen_at"])
        for r in analysis["results"]:
            for point in r["construction"]["history"]:
                for d, values in point["definitions"].items():
                    writer.writerow([r["problem"], d, point["episodes"], *(values[k] for k in
                        ("N", "f1", "f1_over_N", "distinct_answers", "freeze_eligible", "frozen_at"))])
    with (out / "frequencies.csv").open("w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["problem", "definition", "validation_eligible", "coverage_qualified", "answer", "reference_count", "reference_fraction", "port_count", "port_fraction"])
        for r in analysis["results"]:
            for d, data in r["definitions"].items():
                for f in data["frequency_comparison"]:
                    writer.writerow([r["problem"], d, r["construction"]["validation_eligible"], r["coverage_qualified"],
                                     *(f[k] for k in ("answer", "reference_count", "reference_fraction", "port_count", "port_fraction"))])


def analyze(out):
    p, m, seeds, _ = verify_study(out, runtime=False)
    result = summarize(load_rows(out, p, seeds), p, seeds, m["imported_episodes"])
    expected_paths = set()
    for r in result["results"]:
        for d, frozen in r["construction"]["frozen"].items():
            if frozen:
                path = out / "oracles" / r["problem"] / f"{d}.json"
                expected_paths.add(path)
                if not path.exists() or read_json(path) != {"problem": r["problem"], "definition": d, **frozen}:
                    raise ValueError("Frozen oracle file differs from its construction prefix")
    if set((out / "oracles").glob("*/*.json")) != expected_paths:
        raise ValueError("Unexpected frozen oracle file")
    write_reports(out, result)
    return result


def save_oracles(out, name, construction):
    for d, frozen in construction.frozen.items():
        if frozen:
            path = out / "oracles" / name / f"{d}.json"
            value = {"problem": name, "definition": d, **frozen}
            if path.exists():
                if read_json(path) != value:
                    raise ValueError("Frozen oracle changed")
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                write_json(path, value)


def run(args):
    out = args.out.resolve()
    with v1.locked(out):
        p, m, seeds, local = verify_study(out)
        authorize(p, args.allow_full_experiment)
        if (out / "COMPLETE.json").exists():
            print(json.dumps({"already_complete": True, "totals": analyze(out)["totals"]}), flush=True)
            return
        rows = load_rows(out, p, seeds)
        grouped = group_rows(rows, p, seeds)
        states = {}
        for name, phases in grouped.items():
            state = Construction(p["construction"], m["imported_episodes"].get(name, 0))
            for row in ordered(phases["construction"]):
                state.add(row)
            states[name] = state
            save_oracles(out, name, state)
            if phases["validation"] and not state.qualified:
                raise ValueError("Ineligible validation data exist")
        progress = {"state": "running", "started_utc": now(), "completed_episodes": len(rows),
                    "maximum_episodes": len(p["problems"]) * sum(phase_budget(p, ph) for ph in PHASES)}
        deadline = time.monotonic() + p["invocation_timeout_seconds"]

        def status():
            progress.update(updated_utc=now(), construction={name: {
                "episodes": s.episodes, "done": s.done, "validation_eligible": s.qualified,
                "frozen_at": {d: f["at_episode"] if f else None for d, f in s.frozen.items()},
                "rates": {d: s.history[-1]["definitions"][d]["f1_over_N"] if s.history else None for d in DEFINITIONS}}
                for name, s in states.items()})
            write_json(out / "progress.json", progress)

        def execute(task):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("Invocation budget exhausted; completed receipts remain resumable")
            return execute_task(out, task, local, min(remaining, p["episode_timeout_seconds"]))

        def accept(task, row):
            grouped[task["problem"]][task["phase"]][task["episode"]] = row
            rows.append(row)
            progress.update(completed_episodes=len(rows), phase=task["phase"], problem=task["problem"])
            if task["phase"] == "construction":
                state = states[task["problem"]]
                state.add(row)
                save_oracles(out, task["problem"], state)
            status()

        try:
            status()
            with ThreadPoolExecutor(max_workers=p["workers"]) as pool:
                # Only one construction episode per problem is in flight: no stop overshoot.
                queue = deque(i for i, x in enumerate(p["problems"]) if not states[x["name"]].done)
                pending = {}
                while queue or pending:
                    while queue and len(pending) < p["workers"]:
                        pi = queue.popleft()
                        name = p["problems"][pi]["name"]
                        task = task_for(p, seeds, "construction", pi, states[name].episodes)
                        pending[pool.submit(execute, task)] = (pi, task)
                    done, _ = wait(pending, timeout=15, return_when=FIRST_COMPLETED)
                    if not done:
                        status()
                    for future in done:
                        pi, task = pending.pop(future)
                        accept(task, future.result())
                        if not states[task["problem"]].done:
                            queue.append(pi)
                write_reports(out, summarize(rows, p, seeds, m["imported_episodes"]))
                print(json.dumps({"construction_finished": True, "eligible_problems": sum(s.qualified for s in states.values()),
                                  "capped_problems": sum(not s.qualified for s in states.values())}), flush=True)
                for phase in ("validation", "port"):
                    tasks = iter(task_for(p, seeds, phase, pi, ep)
                                 for ep in range(phase_budget(p, phase)) for pi, problem in enumerate(p["problems"])
                                 if (phase == "port" or states[problem["name"]].qualified)
                                 and ep not in grouped[problem["name"]][phase])
                    pending = {}
                    exhausted = False
                    while pending or not exhausted:
                        while len(pending) < p["workers"] and not exhausted:
                            task = next(tasks, None)
                            if task is None:
                                exhausted = True
                            else:
                                pending[pool.submit(execute, task)] = task
                        if not pending:
                            break
                        done, _ = wait(pending, timeout=15, return_when=FIRST_COMPLETED)
                        if not done:
                            status()
                        for future in done:
                            task = pending.pop(future)
                            accept(task, future.result())
                    write_reports(out, summarize(rows, p, seeds, m["imported_episodes"]))
                    print(json.dumps({"phase_finished": phase, "completed_episodes": len(rows)}), flush=True)
            result = analyze(out)
            if not result["complete"]:
                raise ValueError("Study ended without its declared eligible observations")
            write_json(out / "COMPLETE.json", {"finished_utc": now(), "totals": result["totals"],
                       "analysis_sha256": sha(out / "analysis.json"), "protocol_sha256": sha(out / "protocol.json"),
                       "seeds_sha256": sha(out / "seeds.json")})
            progress.update(state="complete", totals=result["totals"])
            status()
        except BaseException as exc:
            # A bounded pool may finish already-running episodes; their receipts survive.
            progress.update(state="failed", error_type=type(exc).__name__, error=str(exc))
            status()
            raise
        print(json.dumps({"state": "complete", "totals": result["totals"]}), flush=True)


def export(out, destination):
    if destination.exists():
        raise ValueError("Refusing to overwrite a public export")
    result = analyze(out)
    if not result["complete"] or not (out / "COMPLETE.json").exists():
        raise ValueError("Only a completed study can be exported")
    p, m, seeds, _ = verify_study(out, runtime=False)
    names = ["protocol.json", "manifest.json", "seeds.json", "analysis.json", "oracles.json", "curves.csv", "frequencies.csv", "REPORT.md", "COMPLETE.json"]
    if (out / "pilot-import.json").exists():
        names.append("pilot-import.json")
    data = {n: (out / n).read_bytes() for n in names}
    data["episodes.json"] = (json.dumps(load_rows(out, p, seeds), indent=2, sort_keys=True) + "\n").encode()
    if any(token in body for body in data.values() for token in (b"/Users/", b"/home/", b"HostName", b"sha256:")):
        raise ValueError("Possible private execution metadata in public export")
    destination.mkdir(parents=True)
    for name, body in data.items():
        (destination / name).write_bytes(body)
    write_json(destination / "SHA256.json", {n: sha(destination / n) for n in sorted(data)})
    verify_export(destination)


def verify_export(directory):
    checks = read_json(directory / "SHA256.json")
    required = {"protocol.json", "manifest.json", "seeds.json", "analysis.json", "oracles.json", "curves.csv", "frequencies.csv", "REPORT.md", "COMPLETE.json", "episodes.json"}
    if (directory / "pilot-import.json").exists():
        required.add("pilot-import.json")
    if set(checks) != required or any(Path(n).name != n or sha(directory / n) != h for n, h in checks.items()):
        raise ValueError("Public bundle checksum mismatch")
    p, m, seeds, _ = verify_study(directory, runtime=False)
    for name in ("study.py", "analysis_tools.py"):
        if sha(HERE / name) != m["source"]["files"][f"studies/episodic-v3/{name}"]:
            raise ValueError("Use the recorded analysis code")
    result = summarize(read_json(directory / "episodes.json"), p, seeds, m["imported_episodes"])
    complete = read_json(directory / "COMPLETE.json")
    if (not result["complete"] or result != read_json(directory / "analysis.json")
            or complete["analysis_sha256"] != sha(directory / "analysis.json")
            or complete["protocol_sha256"] != m["protocol_sha256"] or complete["seeds_sha256"] != m["seeds_sha256"]
            or complete["totals"] != result["totals"]):
        raise ValueError("Saved observations do not reproduce the study")
    if read_json(directory / "oracles.json") != {r["problem"]: r["construction"]["frozen"] for r in result["results"]}:
        raise ValueError("Published frozen oracles differ from the recorded stopping decisions")
    print(f"PASS: {sum(v['episodes'] for v in result['totals'].values())} episodes; all stopping decisions, gates, bounds, and frequencies reproduced; zero engine executions")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("prepare", "run", "analyze", "status", "export"):
        cmd = sub.add_parser(name)
        cmd.add_argument("--out", type=Path, required=True)
        if name in ("prepare", "run"):
            cmd.add_argument("--allow-full-experiment", action="store_true")
        if name == "prepare":
            cmd.add_argument("--protocol", type=Path, default=HERE / "protocol.json")
            cmd.add_argument("--image", default="metacat:local")
            cmd.add_argument("--pilot", type=Path)
        if name == "export":
            cmd.add_argument("--destination", type=Path, required=True)
    sub.add_parser("verify-export").add_argument("directory", type=Path)
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
    elif args.command == "worker":
        sys.exit(port_worker(args.task, args.output))
    elif args.command == "export":
        export(args.out, args.destination)
    else:
        verify_export(args.directory)


if __name__ == "__main__":
    main()
