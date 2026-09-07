"""Individual best-answer discovery statistics. No engine execution or imports."""

from collections import Counter

DEFINITIONS = {"best_a": "quality", "best_b": "preference"}


def select_answer(row, definition, protocol):
    """Earliest co-winner is selected natively before memory order is discarded."""
    return row["best_answers"][definition]


def statistics(rows, definition, protocol):
    selected = [select_answer(r, definition, protocol) for r in rows]
    counts = Counter(a for a in selected if a is not None)
    n = sum(counts.values())
    f1 = sum(count == 1 for count in counts.values())
    return {"episodes": len(rows), "N": n, "f1": f1, "f1_over_N": f1 / n if n else None,
            "distinct_answers": len(counts), "answer_counts": dict(sorted(counts.items())),
            "engine_error_episodes": sum(r["status"] == "engine-error" for r in rows),
            "answerless_episodes": sum(r["status"] == "complete" and not r["answer_runs"] for r in rows),
            "tied_answer_episodes": sum(len(r["outcomes"][DEFINITIONS[definition]].get("answers", [])) > 1 for r in rows),
            "singleton_answers_per_completed_episode": f1 / len(rows) if rows else None}


def discovery_curve(rows, definition, protocol):
    points, previous = [], set()
    for count in range(protocol["checkpoint_every"], len(rows) + 1, protocol["checkpoint_every"]):
        point = statistics(rows[:count], definition, protocol)
        support = set(point["answer_counts"])
        point["new_answers_since_previous_checkpoint"] = sorted(support - previous)
        point["at_or_below_target"] = point["N"] > 0 and point["f1_over_N"] <= protocol["singleton_threshold"]
        points.append(point)
        previous = support
    return {"checkpoints": points,
            "first_observed_target_checkpoint": next((p["episodes"] for p in points if p["at_or_below_target"]), None),
            "latest": statistics(rows, definition, protocol)}
