#!/usr/bin/env python3
"""Summarize and cross-check the published support-v1a analysis; no engine execution."""

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path


ACADEMIC = Path(__file__).resolve().parents[1]
BASE = ACADEMIC / "data/support-v1a"
MODELS = ("fixed-1000", "fixed-5000", "fixed-10000", "fixed-20000", "singleton", "no-discovery")


def read(path):
    return json.loads(path.read_text())


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def summarize(analysis, protocol, complete):
    results = analysis["results"]
    size = protocol["analysis"]["check_batch_size"]
    names = [r["problem"] for r in results]
    assert names == [r["name"] for r in protocol["problems"]]
    assert len(names) == 19 and size == 100
    totals = {phase["name"]: len(names) * phase["runs_per_problem"] for phase in protocol["phases"]}
    assert sum(totals.values()) == complete["total_runs"] == 969000
    comparisons = {phase: Counter() for phase in ("validation", "port")}
    prefixes, per_input, novelty, qualified = [], [], [], []
    for model_name in MODELS:
        models = [r["models"][model_name] for r in results]
        prefixes.append({
            "model": model_name, "construction_runs": sum(m["runs"] for m in models),
            "validation_novel": sum(m["validation"]["novel_draws"] for m in models),
            "port_novel": sum(m["port"]["novel_draws"] for m in models),
            "rule_fired_inputs": sum(m["rule_fired"] is True for m in models)
            if model_name in ("singleton", "no-discovery") else None,
        })
    for result in results:
        model = result["models"]["fixed-20000"]
        counts = model["counts"]
        assert sum(counts.values()) == model["runs"] == 20000
        ordered = sorted(counts, key=lambda k: (-counts[k], k))
        head, mass = [], 0
        for name in ordered:
            head.append(name)
            mass += counts[name]
            if 2 * mass >= model["runs"]:
                break
        assert head == model["head"]
        for phase in comparisons:
            data = model[phase]
            batches = data["batches"]
            assert data["runs"] == len(batches) * size == result["timing"][phase]["runs"]
            novel = Counter()
            for i, batch in enumerate(batches):
                assert batch["batch"] == i and batch["start_index"] == i * size
                assert batch["runs"] == size
                assert set(batch["novel"]).isdisjoint(counts)
                assert batch["novel_draws"] == sum(batch["novel"].values())
                assert batch["hard_error_flag"] == (batch["engine_error_runs"] > 0)
                assert batch["frequency"]["permutations"] == protocol["analysis"]["frequency_permutations"]
                novel.update(batch["novel"])
            recalculated = {
                "runs": sum(b["runs"] for b in batches),
                "novel_draws": sum(novel.values()),
                "novel_batches": sum(bool(b["novel"]) for b in batches),
                "missing_batches": sum(bool(b["missing_head"]) for b in batches),
                "engine_error_runs": sum(b["engine_error_runs"] for b in batches),
                "frequency_rejections_19_input_adjusted": sum(
                    b["frequency"]["p_value"] <= protocol["analysis"]["alpha"] / len(names) for b in batches),
            }
            assert dict(novel) == data["novel"]
            assert all(data[k] == v for k, v in recalculated.items())
            comparisons[phase].update(recalculated)
            comparisons[phase]["batches"] += len(batches)
        val, port = model["validation"], model["port"]
        per_input.append({"problem": result["problem"], "states": len(counts),
                          "validation_novel": val["novel_draws"], "validation_errors": val["engine_error_runs"],
                          "port_novel": port["novel_draws"], "port_errors": port["engine_error_runs"],
                          "port_flag_batches": port["either_flag_batches"],
                          "port_frequency_rejections": port["frequency_rejections_19_input_adjusted"],
                          "validation_upper_95": val["novel_draw_upper_95_per_input"],
                          "validation_upper_family": val["novel_draw_upper_family_adjusted"]})
        if val["novel_draw_upper_95_per_input"] <= 0.0001:
            qualified.append(result["problem"])
        for answer, count in port["novel"].items():
            novelty.append({"problem": result["problem"], "answer": answer, "port_count": count,
                            "validation_count": val["novel"].get(answer, 0)})
    errors = analysis["errors"]
    assert len(errors) == complete["engine_errors"] == comparisons["validation"]["engine_error_runs"] == 3
    assert len({(e["problem"], e["seed"]) for e in errors}) == len(errors)
    assert all(e["state"] == "*ERROR*" and e["phase"] == "validation" for e in errors)
    cost_attempts = analysis["attempts"] + analysis["parent_incomplete_attempts"] + analysis["preflight_attempts"]
    wall = sum(a["wall_seconds"] for a in cost_attempts if a.get("wall_seconds") is not None)
    assert wall == analysis["cost_accounting"]["known_aggregate_attempt_wall_seconds"]
    return {
        "scope": "Published-summary and batch consistency audit; does not rerun engines or permutation simulations",
        "totals": totals, "comparisons": {k: dict(v) for k, v in comparisons.items()},
        "prefixes": prefixes, "per_input": per_input, "port_novelty": novelty,
        "nominal_95_qualified_inputs": qualified, "errors": errors,
        "known_aggregate_attempt_wall_seconds": wall,
        "flagged_port_draws_also_seen_in_validation": sum(r["port_count"] for r in novelty if r["validation_count"]),
    }


def audit():
    analysis, protocol, complete, manifest = (read(BASE / name) for name in
                                             ("analysis.json", "protocol.json", "COMPLETE.json", "manifest.json"))
    for key, filename in (("manifest_sha256", "manifest.json"), ("protocol_sha256", "protocol.json"),
                          ("completion_sha256", "COMPLETE.json")):
        assert analysis[key] == digest(BASE / filename), filename
    assert manifest["protocol_sha256"] == analysis["protocol_sha256"]
    assert complete["manifest_sha256"] == analysis["manifest_sha256"]
    report = summarize(analysis, protocol, complete)
    report["input_sha256"] = {name: digest(BASE / name) for name in
                              ("analysis.json", "protocol.json", "COMPLETE.json", "manifest.json")}
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ACADEMIC / "support-study-audit.json")
    args = parser.parse_args()
    report = audit()
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"totals": report["totals"], "comparisons": report["comparisons"]}, indent=2))


if __name__ == "__main__":
    main()
