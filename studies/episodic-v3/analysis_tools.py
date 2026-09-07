"""Frozen-oracle decisions and saved-data statistics; never execute an engine."""

from collections import Counter
from copy import deepcopy
import math

DEFINITIONS = {"best_a": "quality", "best_b": "preference"}


def counts_summary(counts):
    n = sum(counts.values())
    f1 = sum(value == 1 for value in counts.values())
    return {"N": n, "f1": f1, "f1_over_N": f1 / n if n else None,
            "distinct_answers": len(counts), "answer_counts": dict(sorted(counts.items()))}


class Construction:
    def __init__(self, config, imported_episodes=0):
        self.config = config
        self.imported_episodes = imported_episodes
        self.episodes = 0
        self.counts = {d: Counter() for d in DEFINITIONS}
        self.frozen = dict.fromkeys(DEFINITIONS)
        self.history = []

    @property
    def qualified(self):
        return all(self.frozen.values())

    @property
    def done(self):
        return self.qualified or self.episodes == self.config["max_episodes"]

    def add(self, row):
        if self.done:
            raise ValueError("Construction continued after its stop")
        if row["task"]["episode"] != self.episodes:
            raise ValueError("Construction must follow the recorded episode prefix")
        self.episodes += 1
        points = {}
        for definition in DEFINITIONS:
            answer = row["best_answers"][definition]
            if answer is not None:
                self.counts[definition][answer] += 1
            stats = counts_summary(self.counts[definition])
            eligible = self.episodes >= max(self.config["min_episodes"], self.imported_episodes)
            crossed = stats["N"] > 0 and stats["f1_over_N"] <= self.config["singleton_threshold"]
            if eligible and crossed and self.frozen[definition] is None:
                self.frozen[definition] = {"at_episode": self.episodes, **deepcopy(stats)}
            points[definition] = {k: v for k, v in stats.items() if k != "answer_counts"}
            points[definition].update(freeze_eligible=eligible, at_or_below_target=crossed,
                                     frozen_at=self.frozen[definition]["at_episode"] if self.frozen[definition] else None)
        self.history.append({"episodes": self.episodes, "definitions": points})

    def summary(self):
        return {"episodes": self.episodes, "imported_episodes": self.imported_episodes,
                "stop_reason": "both-thresholds" if self.qualified else (
                    "budget-cap" if self.done else "incomplete"),
                "validation_eligible": self.qualified, "frozen": deepcopy(self.frozen),
                "all_collected": {d: counts_summary(c) for d, c in self.counts.items()},
                "history": deepcopy(self.history)}


def population(rows, definition):
    return {**counts_summary(Counter(r["best_answers"][definition] for r in rows
                                    if r["best_answers"][definition] is not None)),
            "assigned_episodes": len(rows),
            "engine_error_episodes": sum(r["status"] == "engine-error" for r in rows),
            "answerless_episodes": sum(r["status"] == "complete" and r["answer_runs"] == 0 for r in rows)}


def binomial_cdf(k, n, p):
    if p == 0 or k == n:
        return 1.0
    if p == 1:
        return 0.0
    # Log-space evaluation also handles an ordinary outcome at every trial.
    logs = [math.lgamma(n + 1) - math.lgamma(j + 1) - math.lgamma(n - j + 1)
            + j * math.log(p) + (n - j) * math.log1p(-p) for j in range(k + 1)]
    maximum = max(logs)
    return min(1.0, math.exp(maximum) * math.fsum(math.exp(x - maximum) for x in logs))


def upper_bound(misses, n, alpha):
    if type(misses) is not int or type(n) is not int or not 0 <= misses <= n or not 0 < alpha < 1:
        raise ValueError("Invalid binomial counts or confidence level")
    if n == 0:
        return None
    if misses == n:
        return 1.0
    if misses == 0:
        return -math.expm1(math.log(alpha) / n)
    lo, hi = 0.0, 1.0
    for _ in range(70):
        mid = (lo + hi) / 2
        if binomial_cdf(misses, n, mid) > alpha:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def membership(rows, definition, frozen):
    result = population(rows, definition)
    outside = {answer: count for answer, count in result["answer_counts"].items()
               if answer not in frozen["answer_counts"]}
    result.update(outside_counts=outside, outside_occurrences=sum(outside.values()))
    return result


def validate_frozen(rows, definition, frozen, config, eligible):
    if not eligible:
        if rows:
            raise ValueError("Validation was collected for an ineligible problem")
        return {"status": "skipped-threshold-not-met", "upper_bound": None,
                "coverage_claim": False, "note": "Retained construction data are not statistically validated."}
    result = membership(rows, definition, frozen)
    alpha = config["family_alpha"] / config["family_size"]
    finished = len(rows) == config["episodes"]
    bound = upper_bound(result["outside_occurrences"], result["N"], alpha) if finished else None
    result.update(upper_bound=bound, per_population_alpha=alpha,
                  coverage_claim=bound is not None and bound <= config["missing_mass_target"],
                  status="incomplete" if not finished else (
                      "no-answered-episodes" if bound is None else (
                          "qualified" if bound <= config["missing_mass_target"] else "coverage-target-not-met")))
    return result


def frequencies(reference, port):
    n, m = reference["N"], port["N"]
    return [{"answer": a, "reference_count": reference["answer_counts"].get(a, 0),
             "port_count": port["answer_counts"].get(a, 0),
             "reference_fraction": reference["answer_counts"].get(a, 0) / n if n else None,
             "port_fraction": port["answer_counts"].get(a, 0) / m if m else None}
            for a in sorted(reference["answer_counts"].keys() | port["answer_counts"].keys())]
