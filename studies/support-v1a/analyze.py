#!/usr/bin/env python3
"""Analyze the complete, amended campaign; retain errors in all denominators."""

from collections import Counter
import argparse
import importlib.util
from pathlib import Path

from collect import HERE, load_completed, read_json, sha, tasks_for, chunk_dir, write_json, verify_preflight

SPEC = importlib.util.spec_from_file_location("support_v1_analysis", HERE.parent / "support-v1/analyze.py")
legacy = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(legacy)


def summarize_checks(rows, counts, cfg, **kwargs):
    result = legacy.summarize_checks([r["state"] for r in rows], counts, cfg, **kwargs)
    size = cfg["check_batch_size"]
    result["engine_error_runs"] = sum(r["state"] == "*ERROR*" for r in rows)
    result["engine_error_rate"] = result["engine_error_runs"] / len(rows)
    for batch in result["batches"]:
        sample = rows[batch["start_index"]:batch["start_index"] + size]
        batch["engine_error_runs"] = sum(r["state"] == "*ERROR*" for r in sample)
        batch["hard_error_flag"] = batch["engine_error_runs"] > 0
    result["hard_error_batches"] = sum(b["hard_error_flag"] for b in result["batches"])
    result["support_or_hard_error_batches"] = sum(
        bool(b["novel"] or b["missing_head"] or b["hard_error_flag"]) for b in result["batches"])
    return result


def measured_codelets(rows):
    return {"measured_codelets": sum(r["codelets"] for r in rows if r["codelets"] is not None),
            "unknown_codelet_runs": sum(r["codelets"] is None for r in rows)}


def verify_inheritance(out, manifest, complete):
    if sha(out / "parent-import.json") != manifest["parent_import_sha256"]:
        raise ValueError("Parent import hash mismatch")
    imported = read_json(out / "parent-import.json")
    if sha(out / "parent-inventory.json") != imported["parent_inventory_sha256"]:
        raise ValueError("Parent inventory hash mismatch")
    if any(complete["receipts"].get(name) != digest for name, digest in imported["receipts"].items()):
        raise ValueError("Inherited completed receipt changed")
    if complete["preflight_sha256"] != sha(out / "preflight.json"):
        raise ValueError("Preflight record hash mismatch")
    verify_preflight(out)
    return imported


def analyze(out):
    manifest, p, data, attempts = legacy.load_study(out)
    complete = read_json(out / "COMPLETE.json")
    imported = verify_inheritance(out, manifest, complete)
    cfg, results = p["analysis"], []
    errors = [row for phase in data.values() for rows in phase.values() for row in rows if row["state"] == "*ERROR*"]
    if len(errors) != complete["engine_errors"]:
        raise ValueError("Error count differs from completion inventory")
    for i, problem in enumerate(p["problems"]):
        name = problem["name"]
        construction = data["construction"][name]
        states = [r["state"] for r in construction]
        prefixes = {f"fixed-{n}": {"runs": n, "rule_fired": None} for n in cfg["fixed_prefixes"]}
        prefixes.update(legacy.stopping_prefixes(states, cfg))
        models = {}
        for model, decision in prefixes.items():
            n = decision["runs"]
            counts = Counter(states[:n])
            model_result = {**decision, "counts": dict(sorted(counts.items())), "head": legacy.head(counts),
                            "f1_over_n": sum(v == 1 for v in counts.values()) / n,
                            "construction_cost": {**measured_codelets(construction[:n]),
                                "run_seconds": sum(r["elapsed_seconds"] for r in construction[:n])}}
            for j, phase in enumerate(("validation", "port")):
                seed = cfg["frequency_rng_seed"] + i * 100000 + j * 10000 if n == len(states) and model.startswith("fixed-") else None
                model_result[phase] = summarize_checks(data[phase][name], counts, cfg,
                    family_size=len(p["problems"]), frequency_seed=seed)
            models[model] = model_result
        timing = {phase: {"runs": len(data[phase][name]), **measured_codelets(data[phase][name]),
                          "run_seconds": sum(r["elapsed_seconds"] for r in data[phase][name]),
                          "cap_runs": sum(r["state"] == "*CAP*" for r in data[phase][name]),
                          "engine_error_runs": sum(r["state"] == "*ERROR*" for r in data[phase][name])}
                  for phase in data}
        results.append({"problem": name, "models": models, "timing": timing})
        print(f"Analyzed {name}", flush=True)
    parent_incomplete = [a for a in imported["attempts"] if not a["admitted_in_parent"]]
    preflight_attempts = [read_json(path) for path in sorted((out / "preflight").glob("chunks/*/*/*/attempt-*/attempt.json"))]
    cost_attempts = attempts + parent_incomplete + preflight_attempts
    payload = {"study_id": p["study_id"], "manifest_sha256": sha(out / "manifest.json"),
               "protocol_sha256": sha(out / "protocol.json"), "analysis_script_sha256": sha(Path(__file__)),
               "source_commit": manifest["source"]["git_commit"], "completion_sha256": sha(out / "COMPLETE.json"),
               "attempts": attempts, "parent_incomplete_attempts": parent_incomplete,
               "preflight_attempts": preflight_attempts, "errors": errors, "results": results,
               "cost_accounting": {"known_aggregate_attempt_wall_seconds": sum(
                    a["wall_seconds"] for a in cost_attempts if a.get("wall_seconds") is not None),
                    "unknown_wall_time_attempts": sum(a.get("wall_seconds") is None for a in cost_attempts),
                    "qualification": "Aggregate execution time, not campaign elapsed time or CPU time. Includes inherited attempts once, interrupted parent attempts, continuation attempts, and excluded preflight. Earlier interactive diagnosis, human effort, setup, and analysis costs are not fully measured."},
               "qualification": "Post-failure amendment, with inherited and newly collected observations. ERROR is an observed execution outcome, never acceptable behavior. Validation is not merged into construction. Confidence limits are nominal under independent fixed-law sampling assumptions; no claim of an unchanged prospective experiment or universal defect-detection power."}
    write_json(out / "analysis.json", payload)
    lines = ["# Amended Study Results", "", f"Continuation commit: `{payload['source_commit']}`.", "",
             payload["qualification"], "",
             "Complete checksummed fixed-budget campaign. Full construction sets remain frozen.", "",
             "| Input | States | Validation novel / 30000 | Validation errors / 30000 | Port novel / 1000 | Port errors / 1000 | Port support-flag batches / 10 |",
             "| --- | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for row in results:
        m = row["models"]["fixed-20000"]
        val, port = m["validation"], m["port"]
        lines.append(f"| {row['problem']} | {len(m['counts'])} | {val['novel_draws']} | {val['engine_error_runs']} | "
                     f"{port['novel_draws']} | {port['engine_error_runs']} | {port['either_flag_batches']} |")
    lines += ["", "ERROR remains in all fixed-budget denominators and also triggers a separate hard-error flag,",
              "even if a future reference includes the same error category. A port need not reproduce reference defects.",
              "No answer-only conditional analysis silently drops failed executions.",
              "Nominal confidence limits, frequency comparisons, head omissions, and all batch details are in analysis.json.",
              "Error discovery during execution is not attributed specifically to Good-Turing or p50.",
              "No pooled cross-input failure probability or beneficial episodic-learning result is claimed.", ""]
    (out / "RESULTS.md").write_text("\n".join(lines))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    analyze(parser.parse_args().output.resolve())
