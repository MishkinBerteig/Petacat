#!/usr/bin/env python3
"""Analyze only complete, checksummed versioned study records."""

from collections import Counter
import argparse
import json
from pathlib import Path

import numpy as np
from scipy.stats import binomtest

from collect import chunk_dir, load_completed, read_json, sha, tasks_for, write_json


def head(counts):
    if not counts or any(n <= 0 for n in counts.values()):
        raise ValueError("Head requires positive counts")
    result, cumulative = [], 0
    total = sum(counts.values())
    for state, n in sorted(counts.items(), key=lambda item: (-item[1], item[0])):
        result.append(state)
        cumulative += n
        if 2 * cumulative >= total:
            return result


def upper_limit(k, n, alpha=0.05):
    return float(binomtest(k, n, alternative="less").proportion_ci(
        confidence_level=1 - alpha, method="exact").high)


def flags(states, counts):
    produced = Counter(states)
    return {"novel_draws": sum(v for s, v in produced.items() if s not in counts),
            "novel": {s: v for s, v in sorted(produced.items()) if s not in counts},
            "missing_head": [s for s in head(counts) if not produced[s]]}


def frequency_test(reference, observed, permutations, seed):
    labels = sorted(set(reference) | set(observed))
    ref = np.array([reference[s] for s in labels], dtype=np.int64)
    obs = np.array([observed[s] for s in labels], dtype=np.int64)
    nr, no = int(ref.sum()), int(obs.sum())
    if nr <= 0 or no <= 0 or permutations < 1:
        raise ValueError("Frequency test needs positive sample sizes and permutations")
    pooled = ref + obs
    statistic = float(np.abs(ref / nr - obs / no).sum() / 2)
    rng = np.random.default_rng(seed)
    simulated = rng.multivariate_hypergeometric(pooled, no, size=permutations)
    statistics = np.abs((pooled - simulated) / nr - simulated / no).sum(axis=1) / 2
    extreme = int(np.count_nonzero(statistics >= statistic - 1e-12))
    return {"total_variation": statistic, "p_value": (1 + extreme) / (1 + permutations),
            "permutations": permutations, "rng_seed": seed}


def stopping_prefixes(states, cfg):
    counts = Counter()
    latest_discovery = 0
    decisions = {}
    for n, state in enumerate(states, 1):
        if state not in counts:
            latest_discovery = n
        counts[state] += 1
        if n < cfg["heuristic_min_runs"] or n % cfg["heuristic_checkpoint_interval"]:
            continue
        f1 = sum(v == 1 for v in counts.values())
        if ("singleton" not in decisions and f1 / n <= cfg["singleton_threshold"]
                and (f1 > 0 or n >= cfg["zero_singleton_floor"])):
            decisions["singleton"] = {"runs": n, "rule_fired": True}
        if "no-discovery" not in decisions and n - latest_discovery >= cfg["no_discovery_gap"]:
            decisions["no-discovery"] = {"runs": n, "rule_fired": True}
    return {name: decisions.get(name, {"runs": len(states), "rule_fired": False})
            for name in ("singleton", "no-discovery")}


def summarize_checks(states, counts, cfg, *, family_size, frequency_seed=None):
    n = len(states)
    size = cfg["check_batch_size"]
    if n == 0 or n % size:
        raise ValueError("Checks must form complete prespecified batches")
    whole = flags(states, counts)
    batches = []
    for i, start in enumerate(range(0, n, size)):
        sample = states[start:start + size]
        row = {"batch": i, "start_index": start, "runs": size, **flags(sample, counts)}
        if frequency_seed is not None:
            row["frequency"] = frequency_test(counts, Counter(sample), cfg["frequency_permutations"],
                                               frequency_seed + i)
        batches.append(row)
    result = {"runs": n, **whole,
              "novel_draw_rate": whole["novel_draws"] / n,
              "novel_draw_upper_95_per_input": upper_limit(whole["novel_draws"], n, cfg["alpha"]),
              "novel_draw_upper_family_adjusted": upper_limit(whole["novel_draws"], n,
                                                               cfg["alpha"] / family_size),
              "novel_batches": sum(bool(b["novel"]) for b in batches),
              "missing_batches": sum(bool(b["missing_head"]) for b in batches),
              "either_flag_batches": sum(bool(b["novel"] or b["missing_head"]) for b in batches),
              "batches": batches}
    if frequency_seed is not None:
        result["frequency_rejections_per_input"] = sum(b["frequency"]["p_value"] <= cfg["alpha"] for b in batches)
        result["frequency_rejections_19_input_adjusted"] = sum(
            b["frequency"]["p_value"] <= cfg["alpha"] / family_size for b in batches)
    return result


def load_study(out):
    complete = read_json(out / "COMPLETE.json")
    manifest = read_json(out / "manifest.json")
    p = read_json(out / "protocol.json")
    if manifest["pilot"]:
        raise ValueError("Pilot data are excluded from the main analysis")
    if complete["manifest_sha256"] != sha(out / "manifest.json"):
        raise ValueError("Manifest checksum mismatch")
    if manifest["protocol_sha256"] != sha(out / "protocol.json"):
        raise ValueError("Protocol checksum mismatch")
    data, receipts, attempts = {}, {}, []
    for phase in p["phases"]:
        data[phase["name"]] = {x["name"]: [] for x in p["problems"]}
        for task in tasks_for(p, phase):
            directory = chunk_dir(out, task)
            name = str(directory.relative_to(out) / "complete.json")
            receipts[name] = sha(directory / "complete.json")
            rows = load_completed(directory, task)
            if rows is None:
                raise ValueError("Missing completed chunk")
            data[phase["name"]][task["problem"]].extend(rows)
            for attempt in sorted(directory.glob("attempt-*")):
                info = read_json(attempt / "attempt.json")
                attempts.append({"phase": task["phase"], "problem": task["problem"],
                                 "offset": task["offset"], "attempt": attempt.name,
                                 "exit_status": info.get("exit_status"),
                                 "error_type": info.get("error_type"),
                                 "wall_seconds": info.get("wall_seconds")})
        for rows in data[phase["name"]].values():
            if [r["index"] for r in rows] != list(range(phase["runs_per_problem"])):
                raise ValueError("Incomplete or reordered input sequence")
    if receipts != complete["receipts"]:
        raise ValueError("Completion inventory mismatch")
    total = sum(len(rows) for phase in data.values() for rows in phase.values())
    if total != complete["total_runs"]:
        raise ValueError("Completion run total mismatch")
    return manifest, p, data, attempts


def analyze(out):
    manifest, p, data, attempts = load_study(out)
    cfg = p["analysis"]
    results = []
    for i, problem in enumerate(p["problems"]):
        name = problem["name"]
        construction = data["construction"][name]
        states = [r["state"] for r in construction]
        prefixes = {f"fixed-{n}": {"runs": n, "rule_fired": None} for n in cfg["fixed_prefixes"]}
        prefixes.update(stopping_prefixes(states, cfg))
        models = {}
        for model, decision in prefixes.items():
            n = decision["runs"]
            counts = Counter(states[:n])
            model_result = {**decision, "counts": dict(sorted(counts.items())), "head": head(counts),
                            "f1_over_n": sum(v == 1 for v in counts.values()) / n,
                            "construction_codelets": sum(r["codelets"] for r in construction[:n]),
                            "construction_run_seconds": sum(r["elapsed_seconds"] for r in construction[:n])}
            for j, phase in enumerate(("validation", "port")):
                sequence = [r["state"] for r in data[phase][name]]
                seed = cfg["frequency_rng_seed"] + i * 100000 + j * 10000 if n == len(states) and model.startswith("fixed-") else None
                model_result[phase] = summarize_checks(sequence, counts, cfg,
                    family_size=len(p["problems"]), frequency_seed=seed)
            models[model] = model_result
        timing = {phase: {"runs": len(data[phase][name]),
                          "codelets": sum(r["codelets"] for r in data[phase][name]),
                          "run_seconds": sum(r["elapsed_seconds"] for r in data[phase][name]),
                          "cap_runs": sum(r["state"] == "*CAP*" for r in data[phase][name])}
                  for phase in data}
        results.append({"problem": name, "models": models, "timing": timing})
        print(f"Analyzed {name}", flush=True)
    payload = {"study_id": p["study_id"], "manifest_sha256": sha(out / "manifest.json"),
               "protocol_sha256": sha(out / "protocol.json"),
               "analysis_script_sha256": sha(Path(__file__)), "source_commit": manifest["source"]["git_commit"],
               "completion_sha256": sha(out / "COMPLETE.json"), "attempts": attempts, "results": results,
               "qualification": "Finite observed supports; not proof of equivalence. Binomial and permutation assumptions apply. No defect-injection power study."}
    write_json(out / "analysis.json", payload)
    lines = ["# Versioned Study Results", "", f"Source commit: `{payload['source_commit']}`.", "",
             "Complete checksummed study; fixed 20,000-run construction shown below.",
             "Other prefixes, heuristic rules, per-batch comparisons, and all p-values are in `analysis.json`.", "",
             "| Input | States | Held-out novel draws / 30000 | Per-input upper 95% | Port novel draws / 1000 | Port flagged batches / 10 | Frequency rejections / 10 (0.05/19) |",
             "| --- | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for row in results:
        m = row["models"]["fixed-20000"]
        val, port = m["validation"], m["port"]
        lines.append(f"| {row['problem']} | {len(m['counts'])} | {val['novel_draws']} | "
                     f"{val['novel_draw_upper_95_per_input']:.6g} | {port['novel_draws']} | "
                     f"{port['either_flag_batches']} | {port['frequency_rejections_19_input_adjusted']} |")
    lines += ["", "The support diagnostic and frequency comparator test different properties.",
              "Flag counts are not validity judgments or calibrated power estimates.",
              "Confidence limits assume independent draws from a fixed law and a separately frozen reference.",
              "Family-adjusted limits and raw permutation p-values are retained in the JSON.",
              "The 0.05/19 threshold concerns inputs within a batch, not all repeated batches.",
              "Runtime measurements are descriptive under concurrent load and different execution environments.", ""]
    (out / "RESULTS.md").write_text("\n".join(lines))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    analyze(parser.parse_args().output.resolve())
