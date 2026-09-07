#!/usr/bin/env python3
"""Recompute manuscript quantities from saved counts, without new engine runs."""

import hashlib
import json
import math
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "academic/data"
REFERENCE = DATA / "reference-single-runs.json"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def head_members(counts):
    """Match the published derived-set rule, including lexicographic ties."""
    total = sum(counts.values())
    if not counts or any(not isinstance(c, int) or c <= 0 for c in counts.values()):
        raise ValueError("Expected positive integer counts")
    selected, cumulative = [], 0
    for member, count in sorted(counts.items(), key=lambda item: (-item[1], item[0])):
        selected.append(member)
        cumulative += count
        if 2 * cumulative >= total:
            break
    return selected


def binomial_lower_tail(n, p, cutoff):
    return math.fsum(math.comb(n, k) * p ** k * (1 - p) ** (n - k)
                     for k in range(cutoff + 1))


def analytic_examples():
    return {
        "description": "Exact toy-distribution calculations, not engine experiments.",
        "same_support_head_absence": (1 - 0.001) ** 100,
        "zero_singleton_floor_failure": (1 - 0.0002) ** 10000,
        "matched_p85_head_absence": (1 - 0.85) ** 100,
        "reweighted_p20_head_absence": (1 - 0.20) ** 100,
        "binomial_test": {
            "description": "Known Bernoulli null p=0.85; reject if C<=50 in n=100.",
            "null_rejection_probability": binomial_lower_tail(100, 0.85, 50),
            "power_at_p20": binomial_lower_tail(100, 0.20, 50),
        },
        "novel_mass_detection_at_100": {
            str(epsilon): 1 - (1 - epsilon) ** 100
            for epsilon in (0.0001, 0.001, 0.01)
        },
        "independent_zero_discovery_validation": {
            "confidence": 0.95, "target": 0.0001,
            "minimum_fixed_sample": math.ceil(math.log(0.05) / math.log1p(-0.0001)),
        },
    }


def main():
    data = json.loads(REFERENCE.read_text())
    results = []
    head_absences = []
    for row in data["results"]:
        counts, n = row["states"], row["n"]
        assert sum(counts.values()) == n, row["name"]
        assert len(counts) == row["distinct_states"], row["name"]
        f1 = sum(c == 1 for c in counts.values())
        assert f1 == row["f1"], row["name"]
        head = []
        for member in head_members(counts):
            p = counts[member] / n
            absence = (1 - p) ** 100
            head.append({"outcome": member, "count": counts[member],
                         "share": p, "plug_in_absence_at_100": absence})
            head_absences.append(absence)
        assert sum(h["share"] for h in head) >= 0.5, row["name"]
        assert sum(h["share"] for h in head[:-1]) < 0.5, row["name"]
        results.append({"problem": row["name"], "input": row["problem"][1:], "N": n,
                        "distinct": len(counts), "f1": f1, "missing_mass_estimate": f1 / n,
                        "stop_reason": row["stop_reason"], "p50": head})
    cycles = []
    for name in ("vs-metacat-pre-rc-a.json", "vs-metacat.json", "vs-metacat-mlx.json"):
        path = DATA / name
        cycle = json.loads(path.read_text())
        references = {row["name"]: row for row in data["results"]}
        assert {row["problem"] for row in cycle["single"]} == set(references), name
        for row in cycle["single"]:
            assert sum(row["produced"].values()) == row["n"], (name, row["problem"])
            counts = references[row["problem"]]["states"]
            observed = {outcome for outcome, count in row["produced"].items() if count > 0}
            assert sorted(observed - counts.keys()) == sorted(e["member"] for e in row["novel"])
            assert sorted(set(head_members(counts)) - observed) == sorted(row["missing_p50"])
            assert head_members(counts) == row["reference_p50"]
        cycles.append({"file": "data/" + name, "sha256": digest(path),
                       "backend": cycle["backend"], "start_seed": cycle["start_seed"],
                       "working_cap": cycle["max_steps"],
                       "initial_runs": sum(row["n"] for row in cycle["single"]),
                       "cap_resolution_reruns": sum(len(row.get("resolved_at_reference_cap", []))
                                                    for row in cycle["single"]),
                       "novel_problem_outcome_pairs": sum(len(r["novel"]) for r in cycle["single"]),
                       "missing_head_members": sum(len(r["missing_p50"]) for r in cycle["single"]),
                       "novelties": [{"problem": r["problem"], "novel": r["novel"]}
                                     for r in cycle["single"] if r["novel"]]})
    q = [r["missing_mass_estimate"] for r in results]
    output = {
        "description": "Arithmetic audit of saved artifacts, not a new experiment or validation of statistical guarantees.",
        "reference_sha256": digest(REFERENCE), "reference_parameters": data["params"],
        "problems": len(results), "total_reference_runs": sum(r["N"] for r in results),
        "total_observed_problem_outcome_pairs": sum(r["distinct"] for r in results),
        "total_head_members": len(head_absences),
        "zero_singleton_problems": [r["problem"] for r in results if r["f1"] == 0],
        "above_target": [r["problem"] for r in results if r["missing_mass_estimate"] > 1e-4],
        "plug_in_expected_novel_draws_per_cycle": 100 * sum(q),
        "plug_in_expected_flagged_problems_per_cycle": sum(1 - (1 - v) ** 100 for v in q),
        "plug_in_probability_any_novelty_per_cycle": 1 - math.prod((1 - v) ** 100 for v in q),
        "plug_in_maximum_head_absence": max(head_absences),
        "plug_in_cycle_head_union_bound": sum(head_absences),
        "run_count_ratio": sum(r["N"] for r in results) / 1900,
        "same_support_counterexample_head_absence": 0.999 ** 100,
        "zero_singleton_floor_counterexample_probability": (1 - 2e-4) ** 10000,
        "analytic_examples": analytic_examples(),
        "results": results, "saved_cycles": cycles,
    }
    path = ROOT / "academic/number-audit.json"
    path.write_text(json.dumps(output, indent=2) + "\n")
    print(json.dumps({k: v for k, v in output.items() if k not in ("results", "saved_cycles")}, indent=2))


if __name__ == "__main__":
    main()
