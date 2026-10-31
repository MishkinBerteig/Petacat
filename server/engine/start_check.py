"""The run-start check (configuration-source plan 3.4(c); ``ABSENCE-BEHAVIOUR.md`` I-1, I-2).

A configuration that lacks something is a legitimate experiment, and an omitted concept (a
role, a node, a codelet type) is simply unavailable.  Only what the engine cannot invent
stops a run, and it stops it *at the run's start*, with one message listing everything
missing; never at edit time.

* **I-1** the scalars the engine's *declared read list* requires and the configuration lacks:
  formula coefficients, urgency levels (the ones the engine names, the one the opening
  batch names, and the level every codelet pattern entry names).
* **I-2** the opening Coderack cannot be filled: ``initial_codelet_types`` names no codelet
  type the configuration has, and no posting rule exists to post one.

``REQUIRED_FORMULA_COEFFICIENTS`` and ``REQUIRED_URGENCY_LEVELS`` are the declared read
list: the names the engine reads with no fallback today (a missing one is a ``KeyError``
mid-run).  A parameter read with a code default (``get_param(key, default)``) is not on the
list until the defaults are deleted (EN10 adds those names).

The check reads a handful of dictionary keys and builds nothing, so it costs microseconds.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

#: Formula coefficients read by ``meta.get_formula_coeff`` with a literal name, and where.
REQUIRED_FORMULA_COEFFICIENTS: tuple[tuple[str, str], ...] = (
    ("answer_quality_rule_weight", "answers.py, trace.py"),
    ("answer_quality_temperature_weight", "answers.py, trace.py"),
    ("coderack_bin_urgency_exponent_divisor", "coderack.py, capture_projection.py"),
    ("coderack_bin_urgency_exponent_offset", "coderack.py, capture_projection.py"),
    ("group_evaluation_tanh_divisor", "formulas.py"),
    ("low_prob_scale_factor", "formulas.py"),
    ("low_prob_sqrt_base", "formulas.py"),
    ("rule_abstractness_sigmoid_beta", "rules.py"),
    ("rule_abstractness_sigmoid_midpoint", "rules.py"),
    ("rule_abstractness_weight", "rules.py"),
    ("rule_factor_no_supported_rule", "formulas.py, temperature.py"),
    ("rule_factor_weight", "formulas.py, temperature.py"),
    ("rule_factor_with_supported_rule", "formulas.py, temperature.py"),
    ("rule_succinctness_base_cost", "rules.py"),
    ("rule_succinctness_weight", "rules.py"),
    ("rule_uniformity_adjusted_decay_constant", "rules.py"),
    ("rule_uniformity_clause_type_weight", "rules.py"),
    ("rule_uniformity_extrinsic_obj_desc_exponent", "rules.py"),
    ("rule_uniformity_extrinsic_weight", "rules.py"),
    ("rule_uniformity_intrinsic_weight", "rules.py"),
    ("temp_exponent_base", "formulas.py"),
    ("temp_exponent_scale", "formulas.py"),
    ("theme_intra_cluster_neg_to_neg_weight", "themes.py, numeric/layout.py"),
    ("theme_intra_cluster_neg_to_pos_weight", "themes.py, numeric/layout.py"),
    ("theme_intra_cluster_pos_to_neg_weight", "themes.py, numeric/layout.py"),
    ("theme_intra_cluster_pos_to_pos_weight", "themes.py, numeric/layout.py"),
    ("theme_intra_cluster_self_weight", "themes.py, numeric/layout.py"),
    ("theme_net_effect_default_sensitivity", "themes.py, numeric/layout.py"),
    ("unhappiness_weight", "formulas.py, temperature.py"),
)

#: Urgency levels read by ``meta.get_urgency`` with a literal name, and where.
REQUIRED_URGENCY_LEVELS: tuple[tuple[str, str], ...] = (
    ("low", "runner.py, update_cycle.py"),
    ("very_high", "bridges.py"),
    ("very_low", "run_service.py"),
)


@dataclass(frozen=True)
class StartProblem:
    """One thing a run cannot start without."""

    check: str  # "I-1" or "I-2"
    kind: str
    name: str
    where: str

    def __str__(self) -> str:
        return f"{self.kind} '{self.name}' ({self.where})" if self.name else f"{self.kind} ({self.where})"


class RunStartError(Exception):
    """The configuration lacks something the engine cannot invent; ``problems`` lists all."""

    def __init__(self, problems: tuple[StartProblem, ...]) -> None:
        self.problems = problems
        super().__init__(
            "This configuration cannot start a run; it lacks: "
            + "; ".join(str(p) for p in problems)
        )


def check_run_start(meta: Any) -> tuple[StartProblem, ...]:
    """Everything missing, in a fixed order; empty when the run may start."""
    problems: list[StartProblem] = []

    coefficients = meta.formula_coefficients
    for name, where in REQUIRED_FORMULA_COEFFICIENTS:
        if name not in coefficients:
            problems.append(StartProblem("I-1", "formula coefficient", name, where))

    levels = meta.urgency_levels
    for name, where in REQUIRED_URGENCY_LEVELS:
        if name not in levels:
            problems.append(StartProblem("I-1", "urgency level", name, where))
    opening_level = meta.get_param("initial_codelet_urgency")
    if opening_level is not None and opening_level not in levels:
        problems.append(StartProblem("I-1", "urgency level", opening_level, "initial_codelet_urgency"))
    for pattern, entries in meta.codelet_patterns.items():
        for _codelet_type, level in entries:
            if level not in levels:
                problems.append(
                    StartProblem("I-1", "urgency level", level, f"codelet pattern '{pattern}'")
                )

    opening_types = meta.get_param("initial_codelet_types") or []
    if not any(t in meta.codelet_specs for t in opening_types) and not meta.posting_rules:
        problems.append(StartProblem("I-2", "opening Coderack", "", "no codelet can be posted"))

    # One line per distinct problem, order kept.
    return tuple(dict.fromkeys(problems))


def require_run_start(meta: Any) -> None:
    """Raise :class:`RunStartError` naming everything missing; return silently otherwise."""
    problems = check_run_start(meta)
    if problems:
        raise RunStartError(problems)
