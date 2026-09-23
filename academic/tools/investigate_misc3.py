#!/usr/bin/env python3
"""Audit saved misc3 episode winners without importing or running either engine."""

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import statistics


ROOT = Path(__file__).resolve().parents[2]
DEFINITIONS = {"best_a": "quality", "best_b": "preference"}


def read(path):
    return json.loads(path.read_text())


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def audit(base):
    rows = [r for r in read(base / "episodes.json") if r["task"]["problem"] == "misc3"]
    result = next(r for r in read(base / "analysis.json")["results"] if r["problem"] == "misc3")
    frozen = read(base / "oracles.json")["misc3"]
    support = set(frozen["best_a"]["answer_counts"])
    assert support == set(frozen["best_b"]["answer_counts"])
    assert len(rows) == 1111
    report = {
        "scope": "post-hoc saved-data investigation; no engine execution or causal attribution",
        "problem": ["abc", "aabbcc", "kkjjii"],
        "input_sha256": {name: digest(base / name) for name in
                         ("episodes.json", "analysis.json", "oracles.json", "protocol.json", "manifest.json")},
        "frozen": frozen,
        "phases": {},
        "outside_best_a_events": [],
    }
    for phase in ("construction", "validation", "port"):
        selected_rows = [r for r in rows if r["task"]["phase"] == phase]
        qualities = [r["winners"]["quality"][0]["quality"] for r in selected_rows]
        assert all(r["status"] == "complete" for r in selected_rows)
        assert all(r["task"]["strings"] == report["problem"] for r in selected_rows)
        assert all(r["attempted_runs"] == 8 and r["task"]["max_codelets"] == 100000 for r in selected_rows)
        totals = {k: sum(r[k] for r in selected_rows) for k in
                  ("attempted_runs", "answer_runs", "capped_runs", "answerless_runs", "codelets")}
        assert totals["attempted_runs"] == sum(totals[k] for k in
                                              ("answer_runs", "capped_runs", "answerless_runs"))
        phase_result = {
            "episodes": len(selected_rows), "totals": totals,
            "episodes_with_caps": sum(r["capped_runs"] > 0 for r in selected_rows),
            "best_a_quality": {"min": min(qualities), "median": statistics.median(qualities),
                               "max": max(qualities), "above_90": sum(q > 90 for q in qualities)},
            "definitions": {},
        }
        for definition, projection in DEFINITIONS.items():
            counts = Counter(r["best_answers"][definition] for r in selected_rows)
            outside = {a: n for a, n in sorted(counts.items()) if a not in support}
            phase_result["definitions"][definition] = {
                "counts": dict(sorted(counts.items())), "outside_counts": outside,
                "outside_occurrences": sum(outside.values()),
                "episodes_with_outside_cowinners": sum(any(w["answer"] not in support for w in
                                                           r["winners"][projection]) for r in selected_rows),
                "multiple_winning_strings": sum(len(r["outcomes"][projection]["answers"]) > 1
                                                for r in selected_rows),
            }
            for row in selected_rows:
                winners = row["winners"][projection]
                assert row["best_answers"][definition] in {w["answer"] for w in winners}
                assert row["outcomes"][projection]["answers"] == sorted({w["answer"] for w in winners})
            if phase in ("validation", "port"):
                published = result["definitions"][definition]["validation" if phase == "validation" else "port_membership"]
                assert dict(counts) == published["answer_counts"]
                assert outside == published["outside_counts"]
                if phase == "validation":
                    phase_result["definitions"][definition].update(
                        upper_bound=published["upper_bound"], status=published["status"])
        report["phases"][phase] = phase_result

    for row in rows:
        if row["task"]["phase"] != "port" or row["best_answers"]["best_a"] in support:
            continue
        quality_winners = row["winners"]["quality"]
        preference_winners = row["winners"]["preference"]
        maximum = quality_winners[0]["quality"]
        assert all(w["quality"] == maximum for w in quality_winners)
        assert all(w["quality"] <= maximum for w in preference_winners)
        selected = [w for w in quality_winners if w["answer"] == row["best_answers"]["best_a"]]
        names = sorted({w["answer"] for w in quality_winners})
        inside = [w for w in quality_winners + preference_winners if w["answer"] in support]
        inside_ties = sorted(support.intersection(names))
        partition = ("inside-outside-quality-tie" if inside_ties else
                     "outside-only-quality-tie" if len(names) > 1 else "single-outside-winning-string")
        report["outside_best_a_events"].append({
            "episode_index": row["task"]["episode"], "episode_number": row["task"]["episode"] + 1,
            "first_seed": row["task"]["first_seed"], "best_a": row["best_answers"]["best_a"],
            "best_b": row["best_answers"]["best_b"], "quality": maximum,
            "quality_cowinner_strings": names, "inside_quality_cowinner_strings": inside_ties,
            "quality_cowinner_occurrences": len(quality_winners),
            "highest_saved_inside_quality": max((w["quality"] for w in inside), default=None),
            "answer_runs": row["answer_runs"], "capped_runs": row["capped_runs"],
            "answerless_runs": row["answerless_runs"], "diagnostic_partition": partition,
            "selected_descriptions": selected,
            "selected_description_is_undefeated": any(w in preference_winners for w in selected),
        })
    events = report["outside_best_a_events"]
    assert len(events) == 24
    assert all(e["selected_description_is_undefeated"] for e in events)
    report["outside_best_a_summary"] = {
        "episodes": len(events), "distinct_strings": len({e["best_a"] for e in events}),
        "diagnostic_partitions_not_root_causes": dict(Counter(e["diagnostic_partition"] for e in events)),
        "with_caps": sum(e["capped_runs"] > 0 for e in events),
        "all_eight_runs_answered": sum(e["answer_runs"] == 8 for e in events),
        "with_answerless_inner_runs": sum(e["answerless_runs"] > 0 for e in events),
        "saved_inside_answer_present": sum(e["highest_saved_inside_quality"] is not None for e in events),
        "same_best_a_and_best_b": sum(e["best_a"] == e["best_b"] for e in events),
    }
    all_names = sorted({name for phase in report["phases"].values()
                        for d in phase["definitions"].values() for name in d["counts"]})
    report["answer_table"] = [{
        "answer": name,
        "frozen_a": frozen["best_a"]["answer_counts"].get(name, 0),
        "frozen_b": frozen["best_b"]["answer_counts"].get(name, 0),
        **{f"{phase}_{d}": report["phases"][phase]["definitions"][d]["counts"].get(name, 0)
           for phase in ("validation", "port") for d in DEFINITIONS},
    } for name in all_names]
    validation = report["phases"]["validation"]["definitions"]
    port = report["phases"]["port"]["definitions"]
    assert set(port["best_a"]["outside_counts"]) <= set(validation["best_b"]["counts"])
    assert set(port["best_b"]["outside_counts"]) <= set(validation["best_b"]["counts"])
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = audit(ROOT / "studies/episodic-v3/results/main")
    encoded = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded)
        print(json.dumps(report["outside_best_a_summary"], indent=2))
    else:
        print(encoded, end="")


if __name__ == "__main__":
    main()
