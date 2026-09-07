#!/usr/bin/env python3
"""Audit archived episode sequences without running either engine."""

from collections import Counter
import hashlib
import json
from pathlib import Path

ACADEMIC = Path(__file__).resolve().parents[1]
NONANSWERS = {"*NONE*", "*CAP*"}


def last_answer(sequence):
    return next((state for state in reversed(sequence) if state not in NONANSWERS), None)


def audit_problem(row, horizon, episodes, single_support):
    sequences = row["sequences"]
    if len(sequences) != episodes or row["n"] != episodes:
        raise ValueError(f"Episode count mismatch: {row['problem']}")
    if any(len(sequence) != horizon for sequence in sequences):
        raise ValueError(f"Episode horizon mismatch: {row['problem']}")
    endings = [last_answer(sequence) for sequence in sequences]
    counts = Counter(state for state in endings if state is not None)
    if counts != row["produced"]:
        raise ValueError(f"Stored final-answer counts disagree: {row['problem']}")
    never_answered = sum(state is None for state in endings)
    if never_answered != row["episodes_never_answering"]:
        raise ValueError(f"Stored no-answer count disagrees: {row['problem']}")
    missing = sorted(set(row["reference_p50"]) - counts.keys())
    if missing != sorted(row["missing_p50"]):
        raise ValueError(f"Stored missing-head flags disagree: {row['problem']}")
    novel = []
    if len({entry["member"] for entry in row["novel"]}) != len(row["novel"]):
        raise ValueError(f"Duplicate novel outcome: {row['problem']}")
    for entry in row["novel"]:
        state = entry["member"]
        if entry["count"] != counts[state] or counts[state] == 0:
            raise ValueError(f"Stored novelty count disagrees: {row['problem']}")
        in_single = state in single_support
        if "in_single_run_set" in entry and entry["in_single_run_set"] != in_single:
            raise ValueError(f"Stored single-run membership disagrees: {row['problem']}")
        novel.append({"member": state, "count": counts[state], "in_single_run_set": in_single})
    return {"problem": row["problem"], "episodes": episodes, "runs": episodes * horizon,
            "stored_novel_pairs": len(novel), "stored_novel_episodes": sum(e["count"] for e in novel),
            "stored_novel_outside_single_pairs": sum(not e["in_single_run_set"] for e in novel),
            "stored_novel_outside_single_episodes": sum(e["count"] for e in novel if not e["in_single_run_set"]),
            "missing_head_members": len(missing), "episodes_never_answering": never_answered,
            "capped_runs": sum(state == "*CAP*" for sequence in sequences for state in sequence),
            "episodes_with_cap": sum("*CAP*" in sequence for sequence in sequences),
            "episodes_last_run_capped": sum(sequence[-1] == "*CAP*" for sequence in sequences),
            "position_counts": [dict(sorted(Counter(s[i] for s in sequences).items())) for i in range(horizon)],
            "endpoint_counts_including_no_answer": {**dict(sorted(counts.items())), "*NO_ANSWER*": never_answered},
            "stored_reference_f1_over_n": row["reference_f1_over_n"], "novelties": novel}


def audit_cycle(path, reference):
    cycle = json.loads(path.read_text())
    rows = cycle["episodic"]
    if len(rows) != len(reference) or {row["problem"] for row in rows} != set(reference):
        raise ValueError("Input inventory mismatch")
    horizon, episodes = cycle["runs_per_episode"], cycle["tries_per_problem"]
    results = [audit_problem(row, horizon, episodes, reference[row["problem"]]) for row in rows]
    totals = {key: sum(row[key] for row in results) for key in (
        "episodes", "runs", "stored_novel_pairs", "stored_novel_episodes",
        "stored_novel_outside_single_pairs", "stored_novel_outside_single_episodes",
        "missing_head_members", "episodes_never_answering", "capped_runs",
        "episodes_with_cap", "episodes_last_run_capped")}
    return {"file": "data/" + path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "backend": cycle["backend"], "episode_horizon": horizon,
            "start_seed": cycle.get("start_seed", 900000),
            "seed_source": "stored" if "start_seed" in cycle else "historical harness/documentation, not JSON",
            "working_cap": cycle["max_steps"], "reference_cap": cycle.get("reference_max_steps"),
            "totals": totals, "results": results}


def main():
    reference_path = ACADEMIC / "data/reference-single-runs.json"
    data = json.loads(reference_path.read_text())
    reference = {row["name"]: set(row["states"]) for row in data["results"]}
    cycles = [audit_cycle(ACADEMIC / "data" / name, reference) for name in (
        "vs-metacat-pre-rc-a.json", "vs-metacat.json", "vs-metacat-mlx.json")]
    output = {"description": "Archived-data arithmetic audit, not a new engine experiment.",
              "reference_single_runs_sha256": hashlib.sha256(reference_path.read_bytes()).hexdigest(),
              "limitations": [
                  "Historical episodic reference counts and sampled builds are not verified by this audit.",
                  "Novel lists are checked for internal count consistency, not independently derived from an episodic reference.",
                  "Single-run support membership does not establish validity in an episode context.",
                  "Last answer in a fixed horizon is not evidence of convergence or beneficial learning.",
                  "Archived caps differ and same-seed before/after cycles are paired, not independent replications."],
              "cycles": cycles}
    (ACADEMIC / "episode-audit.json").write_text(json.dumps(output, indent=2) + "\n")
    print(json.dumps([{k: v for k, v in cycle.items() if k != "results"} for cycle in cycles], indent=2))


if __name__ == "__main__":
    main()
