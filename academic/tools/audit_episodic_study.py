#!/usr/bin/env python3
"""Audit all episodic v3 comparisons from saved selections; never run an engine."""

import argparse
from collections import Counter, defaultdict
from fractions import Fraction
import hashlib
import json
from pathlib import Path


ACADEMIC = Path(__file__).resolve().parents[1]
BASE = ACADEMIC.parent / "studies/episodic-v3/results/main"
DEFINITIONS = ("best_a", "best_b")
PHASES = ("construction", "validation", "port")
RUN_FIELDS = ("attempted_runs", "answer_runs", "answerless_runs", "capped_runs")


def counts(rows, definition):
    return dict(sorted(Counter(r["best_answers"][definition] for r in rows
                               if r["best_answers"][definition] is not None).items()))


def accounting(rows):
    return {
        "episodes": len(rows),
        "answered_episodes": sum(r["status"] == "complete" and r["answer_runs"] > 0 for r in rows),
        "answerless_episodes": sum(r["status"] == "complete" and r["answer_runs"] == 0 for r in rows),
        "engine_error_episodes": sum(r["status"] == "engine-error" for r in rows),
        "episodes_with_cap": sum(r["capped_runs"] > 0 for r in rows),
        **{key: sum(r[key] for r in rows) for key in RUN_FIELDS},
        "error_runs": sum(r["attempted_runs"] - r["answer_runs"] - r["answerless_runs"]
                          - r["capped_runs"] for r in rows),
    }


def check_population(saved, rows, definition):
    observed = counts(rows, definition)
    assert saved["answer_counts"] == observed
    assert saved["N"] == sum(observed.values())
    totals = accounting(rows)
    for key in ("answerless_episodes", "engine_error_episodes"):
        assert saved[key] == totals[key]
    assert saved["assigned_episodes"] == len(rows)
    assert saved["N"] + totals["answerless_episodes"] + totals["engine_error_episodes"] == len(rows)
    return observed


def frequency_summary(reference, port):
    n, m = sum(reference.values()), sum(port.values())
    assert n > 0 and m > 0
    rows = [{"answer": a, "reference_count": reference.get(a, 0), "port_count": port.get(a, 0),
             "reference_fraction": reference.get(a, 0) / n, "port_fraction": port.get(a, 0) / m}
            for a in sorted(reference.keys() | port.keys())]
    gaps = {a: abs(Fraction(reference.get(a, 0), n) - Fraction(port.get(a, 0), m))
            for a in reference.keys() | port.keys()}
    largest = min(gaps, key=lambda a: (-gaps[a], a))
    return {"reference_N": n, "port_N": m,
            "empirical_tv": float(sum(gaps.values()) / 2),
            "largest_gap": next(r for r in rows if r["answer"] == largest),
            "frequencies": rows}


def summarize(analysis, episodes):
    names = [r["problem"] for r in analysis["results"]]
    assert len(names) == len(set(names)) == 19 and analysis["complete"]
    grouped = defaultdict(list)
    seen = set()
    for row in episodes:
        task = row["task"]
        key = task["problem"], task["phase"], task["episode"]
        assert key not in seen and key[0] in names and key[1] in PHASES
        seen.add(key)
        assert row["status"] in ("complete", "engine-error")
        answered = row["status"] == "complete" and row["answer_runs"] > 0
        assert all((row["best_answers"][d] is not None) == answered for d in DEFINITIONS)
        error_runs = row["attempted_runs"] - sum(row[k] for k in RUN_FIELDS[1:])
        assert error_runs == (row["status"] == "engine-error")
        assert task["episode_runs"] == 8 and task["max_codelets"] == 100000
        assert 1 <= row["attempted_runs"] <= 8
        if row["status"] == "complete":
            assert row["attempted_runs"] == 8
        grouped[key[:2]].append(row)
    for rows in grouped.values():
        rows.sort(key=lambda r: r["task"]["episode"])
        assert [r["task"]["episode"] for r in rows] == list(range(len(rows)))
    totals = {p: accounting([r for r in episodes if r["task"]["phase"] == p]) for p in PHASES}
    for phase, total in totals.items():
        for key in (*RUN_FIELDS, "episodes", "engine_error_episodes"):
            assert total[key] == analysis["totals"][phase][key]
    results, capped, qualified = [], [], []
    for result in analysis["results"]:
        name = result["problem"]
        ref, val, port = (grouped[name, p] for p in PHASES)
        assert len(port) == 100
        construction = result["construction"]
        eligible = construction["validation_eligible"]
        assert len(ref) == construction["episodes"]
        assert len(val) == (1000 if eligible else 0)
        assert result["phase_episodes"] == dict(zip(PHASES, map(len, (ref, val, port))))
        definitions = {}
        for d in DEFINITIONS:
            saved = result["definitions"][d]
            ref_counts = check_population(saved["reference_all_collected"], ref, d)
            port_counts = check_population(saved["port"], port, d)
            frequency = frequency_summary(ref_counts, port_counts)
            assert frequency["frequencies"] == saved["frequency_comparison"]
            frozen = construction["frozen"][d]
            outside = None
            if frozen is not None:
                frozen_counts = counts(ref[:frozen["at_episode"]], d)
                assert frozen["answer_counts"] == frozen_counts
                assert frozen["N"] == sum(frozen_counts.values())
                outside = {a: n for a, n in port_counts.items() if a not in frozen_counts}
                check_population(saved["port_membership"], port, d)
                assert saved["port_membership"]["outside_counts"] == outside
                assert saved["port_membership"]["outside_occurrences"] == sum(outside.values())
            else:
                assert saved["port_membership"] is None
            validation = saved["validation"]
            if eligible:
                val_counts = check_population(validation, val, d)
                val_outside = {a: n for a, n in val_counts.items() if a not in frozen_counts}
                assert validation["outside_counts"] == val_outside
                assert validation["outside_occurrences"] == sum(val_outside.values())
                assert validation["coverage_claim"] == (validation["upper_bound"] <= 0.01)
            else:
                assert validation["status"] == "skipped-threshold-not-met"
                assert validation["upper_bound"] is None and not validation["coverage_claim"]
            definitions[d] = {
                "port_N": sum(port_counts.values()), "outside_counts": outside,
                "outside_occurrences": None if outside is None else sum(outside.values()),
                "coverage_qualified": validation["coverage_claim"],
                "validation_status": validation["status"], "frequency_comparison": frequency,
            }
            if validation["coverage_claim"]:
                qualified.append({"problem": name, "definition": d, "port_N": sum(port_counts.values()),
                                  "outside_occurrences": sum(outside.values())})
            if not eligible:
                capped.append({"problem": name, "definition": d, **frequency})
        results.append({"problem": name, "validation_eligible": eligible,
                        "port": accounting(port), "definitions": definitions})
    return {
        "scope": "Saved episode-selection and accounting audit; no engine execution or new inferential test",
        "frequency_reference": "All collected construction episodes only; no validation pooling or oracle enlargement",
        "totals": totals, "results": results, "capped_frequency_comparisons": capped,
        "qualified_populations": qualified,
    }


def audit():
    hashes = json.loads((BASE / "SHA256.json").read_text())
    inputs = {}
    for name in ("analysis.json", "episodes.json"):
        content = (BASE / name).read_bytes()
        assert hashlib.sha256(content).hexdigest() == hashes[name], name
        inputs[name] = json.loads(content)
    report = summarize(inputs["analysis.json"], inputs["episodes.json"])
    report["input_sha256"] = {name: hashes[name] for name in inputs}
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ACADEMIC / "episodic-study-audit.json")
    args = parser.parse_args()
    report = audit()
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"totals": report["totals"], "qualified_populations": report["qualified_populations"]}, indent=2))


if __name__ == "__main__":
    main()
