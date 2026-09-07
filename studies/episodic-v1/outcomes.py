"""Episode reductions and descriptive statistics; no engine imports or execution."""

from collections import Counter
import json
import math

PROJECTIONS = ("quality", "preference")


def key(outcome):
    return json.dumps(outcome, sort_keys=True, separators=(",", ":"))


def answer_outcome(names):
    names = sorted(set(names))
    return {"kind": "answers", "answers": names} if names else {"kind": "no-answer"}


def preference(a, b, comparable=True, same_themes=True):
    """Independent specification of answers.ss:825-882; -1 prefers a, +1 b."""
    if not a["coherent"] and not b["coherent"]:
        x = (a["theme_abstractness"], a["theme_count"])
        y = (b["theme_abstractness"], b["theme_count"])
        if x != y and all(i <= j for i, j in zip(x, y)):
            return -1
        if x != y and all(j <= i for i, j in zip(x, y)):
            return 1
        return 0
    if a["coherent"] != b["coherent"]:
        return -1 if a["coherent"] else 1
    if a["unjustified_count"] != b["unjustified_count"]:
        return -1 if a["unjustified_count"] < b["unjustified_count"] else 1
    if comparable and same_themes and a["rule_abstractness"] != b["rule_abstractness"]:
        return -1 if a["rule_abstractness"] > b["rule_abstractness"] else 1
    if a["theme_count"] != b["theme_count"]:
        return -1 if a["theme_count"] > b["theme_count"] else 1
    return 0


def reduce_answers(answers, judge):
    """Compare occurrences first, collapse spelling only after selecting winners."""
    if not answers:
        return {p: answer_outcome([]) for p in PROJECTIONS}, {p: [] for p in PROJECTIONS}
    best = max(a["quality"] for a in answers)
    quality = [i for i, a in enumerate(answers) if a["quality"] == best]
    edges = [set() for _ in answers]
    for i in range(len(answers)):
        for j in range(i + 1, len(answers)):
            forward, reverse = judge(i, j), judge(j, i)
            if forward not in (-1, 0, 1) or reverse != -forward:
                raise ValueError("Asymmetric or invalid pairwise preference")
            if forward:
                winner, loser = (i, j) if forward == -1 else (j, i)
                edges[winner].add(loser)
    incoming = [sum(i in e for e in edges) for i in range(len(answers))]
    preferred = [i for i, count in enumerate(incoming) if count == 0]
    remaining, processed = incoming[:], 0
    queue = preferred[:]
    while queue:
        i = queue.pop()
        processed += 1
        for j in edges[i]:
            remaining[j] -= 1
            if remaining[j] == 0:
                queue.append(j)
    if processed != len(answers):
        raise ValueError("Cyclic native preference; preserve attempt and review selector policy")
    indices = {"quality": quality, "preference": preferred}
    winners = {p: sorted((answers[i] for i in ids), key=key) for p, ids in indices.items()}
    return {p: answer_outcome(a["answer"] for a in winners[p]) for p in PROJECTIONS}, winners


def population(rows, projection):
    counts = Counter(key(row["outcomes"][projection]) for row in rows)
    n = len(rows)
    f1 = sum(c == 1 for c in counts.values())
    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    head, mass = [], 0
    for encoded, count in ranked:
        if 2 * mass >= n:
            break
        head.append(json.loads(encoded))
        mass += count
    return {"N": n, "f1": f1, "f1_over_N": f1 / n if n else None,
            "distinct_outcomes": len(counts), "p50": head,
            "p50_empirical_mass": mass / n if n else None,
            "counts": [{"outcome": json.loads(k), "count": v} for k, v in ranked]}


def stopping_history(rows, config):
    history, streak, stop_n = [], 0, None
    for n in range(config["checkpoint_every"], len(rows) + 1, config["checkpoint_every"]):
        rates = {p: population(rows[:n], p)["f1_over_N"] for p in PROJECTIONS}
        passed = n >= config["min_episodes"] and all(
            value <= config["singleton_threshold"] for value in rates.values())
        streak = streak + 1 if passed else 0
        history.append({"N": n, "rates": rates, "both_below_threshold": passed,
                        "consecutive_passing_checkpoints": streak})
        if streak >= config["consecutive_checkpoints"]:
            stop_n = n
            break
    return history, stop_n


def compare(reference, checks, projection):
    observed = Counter(key(r["outcomes"][projection]) for r in reference)
    produced = Counter(key(r["outcomes"][projection]) for r in checks)
    ref_letters = {a for row in reference for a in row["outcomes"][projection].get("answers", [])}
    new_letters = {a for row in checks for a in row["outcomes"][projection].get("answers", [])} - ref_letters
    novel_n = sum(c for k, c in produced.items() if k not in observed)
    n = len(checks)
    return {"N": n, "novel_outcome_episodes": novel_n,
            "novel_outcome_fraction": novel_n / n if n else None,
            "novel_outcomes": [{"outcome": json.loads(k), "count": c}
                               for k, c in sorted(produced.items()) if k not in observed],
            "new_individual_answer_strings": sorted(new_letters),
            "missing_p50": [x for x in population(reference, projection)["p50"] if key(x) not in produced],
            "zero_novelty_nominal_95_percent_upper": -math.expm1(math.log(0.05) / n)
                if n and not novel_n else None,
            "note": "Novel sets, novel member strings, and missing heads are different observations; none alone diagnoses a defect."}
