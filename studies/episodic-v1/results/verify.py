#!/usr/bin/env python3
"""Verify and recompute a published episodic result bundle; never run an engine."""

import argparse
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import collect
from outcomes import PROJECTIONS, compare, population, stopping_history


def verify(directory):
    checksums = collect.read_json(directory / "SHA256.json")
    expected = {"episodes.json", "analysis.json", "manifest.json", "protocol.json", "COMPLETE.json"}
    if set(checksums) != expected:
        raise ValueError("Incomplete published bundle")
    for name, digest in checksums.items():
        if collect.sha(directory / name) != digest:
            raise ValueError(f"Artifact checksum mismatch: {name}")
    manifest = collect.read_json(directory / "manifest.json")
    for name in ("collect.py", "outcomes.py"):
        if collect.sha(HERE.parent / name) != manifest["source"]["files"][f"studies/episodic-v1/{name}"]:
            raise ValueError(f"Use the recorded analysis-tool version: {name}")
    protocol = collect.read_json(directory / "protocol.json")
    collect.validate_protocol(protocol)
    if collect.sha(directory / "protocol.json") != manifest["protocol_sha256"]:
        raise ValueError("Protocol differs from recorded preparation")
    recorded = collect.read_json(directory / "analysis.json")
    complete = collect.read_json(directory / "COMPLETE.json")
    if (collect.sha(directory / "analysis.json") != complete["analysis_sha256"]
            or complete["protocol_sha256"] != manifest["protocol_sha256"]):
        raise ValueError("Completion receipt mismatch")
    rows = collect.read_json(directory / "episodes.json")
    indexed = {}
    problem_indices = {p["name"]: i for i, p in enumerate(protocol["problems"])}
    for row in rows:
        task = row["task"]
        phase, name, episode = task["phase"], task["problem"], task["episode"]
        limit = (protocol["construction"]["max_episodes"] if phase == "construction"
                 else protocol.get(f"{phase}_episodes", 0))
        if (name not in problem_indices or type(episode) is not int or not 0 <= episode < limit
                or (phase, name, episode) in indexed):
            raise ValueError("Invalid or duplicated episode assignment")
        collect.validate_row(row, collect.task_for(protocol, phase, problem_indices[name], episode))
        indexed[phase, name, episode] = row

    recomputed = []
    for problem in protocol["problems"]:
        name = problem["name"]
        phases = {}
        for phase in ("construction", "validation", "port"):
            ids = sorted(i for ph, pr, i in indexed if (ph, pr) == (phase, name))
            if ids != list(range(len(ids))):
                raise ValueError("Episode allocation has gaps")
            phases[phase] = [indexed[phase, name, i] for i in ids]
        reference = phases["construction"]
        history, stop = stopping_history(reference, protocol["construction"])
        reason = "heuristic-target" if stop is not None else "budget-exhausted"
        if (len(reference) != (stop or protocol["construction"]["max_episodes"])
                or any(len(phases[ph]) != protocol[f"{ph}_episodes"] for ph in ("validation", "port"))):
            raise ValueError("Collection violates the declared stopping rule or fixed check sizes")
        recomputed.append({"problem": name, "construction_stop_reason": reason,
            "checkpoints": history, "phase_counts": {ph: len(rs) for ph, rs in phases.items()},
            "populations": {pr: {"reference": population(reference, pr),
                "validation": compare(reference, phases["validation"], pr),
                "port": compare(reference, phases["port"], pr)} for pr in PROJECTIONS}})
    totals = {"episodes": len(rows), "attempted_inner_runs": sum(r["attempted_runs"] for r in rows),
              "engine_error_episodes": sum(r["status"] == "engine-error" for r in rows),
              "capped_inner_runs": sum(r["capped_runs"] for r in rows)}
    if (recorded["results"] != recomputed or recorded["totals"] != totals
            or complete["totals"] != totals or recorded["complete"] is not True
            or recorded["study_id"] != protocol["study_id"]
            or recorded["study_kind"] != protocol["study_kind"]):
        raise ValueError("Saved analysis differs from recomputed observations")
    print(f"PASS: {len(rows)} episodes verified; all statistics reproduced; zero engine executions")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path, nargs="?", default=HERE / "smoke-01")
    verify(parser.parse_args().directory)
